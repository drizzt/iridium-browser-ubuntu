#!/usr/bin/python
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Integration tests for cidb.py module.

Running these tests requires and assumes:
  1) You are running from a machine with whitelisted access to the CIDB
database test instance.
  2) You have a checkout of the crostools repo, which provides credentials
to the above test instance.
"""

# pylint: disable-msg= W0212

import datetime
import glob
import logging
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from chromite.cbuildbot import constants
from chromite.cbuildbot import metadata_lib
from chromite.lib import cidb
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import parallel

SERIES_0_TEST_DATA_PATH = os.path.join(
    constants.CHROMITE_DIR, 'cidb', 'test_data', 'series_0')

TEST_DB_CRED_ROOT = os.path.join(constants.SOURCE_ROOT,
                                 'crostools', 'cidb',
                                 'cidb_test_root')

TEST_DB_CRED_READONLY = os.path.join(constants.SOURCE_ROOT,
                                     'crostools', 'cidb',
                                     'cidb_test_readonly')

TEST_DB_CRED_BOT = os.path.join(constants.SOURCE_ROOT,
                                'crostools', 'cidb',
                                'cidb_test_bot')


class CIDBIntegrationTest(cros_test_lib.TestCase):
  """Base class for cidb tests that connect to a test MySQL instance."""

  def _PrepareFreshDatabase(self, max_schema_version=None):
    """Create an empty database with migrations applied.

    Args:
      max_schema_version: The highest schema version migration to apply,
      defaults to None in which case all migrations will be applied.

    Returns:
      A CIDBConnection instance, connected to a an empty database as the
      root user.
    """
    # Connect to database and drop its contents.
    db = cidb.CIDBConnection(TEST_DB_CRED_ROOT)
    db.DropDatabase()

    # Connect to now fresh database and apply migrations.
    db = cidb.CIDBConnection(TEST_DB_CRED_ROOT)
    db.ApplySchemaMigrations(max_schema_version)

    return db

class CIDBMigrationsTest(CIDBIntegrationTest):
  """Test that all migrations apply correctly."""

  def testMigrations(self):
    """Test that all migrations apply in bulk correctly."""
    self._PrepareFreshDatabase()


  def testIncrementalMigrations(self):
    """Test that all migrations apply incrementally correctly."""
    db = self._PrepareFreshDatabase(0)
    migrations = db._GetMigrationScripts()
    max_version = migrations[-1][0]

    for i in range(1, max_version+1):
      db.ApplySchemaMigrations(i)


class CIDBAPITest(CIDBIntegrationTest):
  """Tests of the CIDB API."""

  def testSchemaVersionTooLow(self):
    """Tests that the minimum_schema decorator works as expected."""
    db = self._PrepareFreshDatabase(3)
    self.assertRaises2(cidb.UnsupportedMethodException,
                       db.InsertBuildStages, [])

  def testSchemaVersionOK(self):
    """Tests that the minimum_schema decorator works as expected."""
    db = self._PrepareFreshDatabase(4)
    db.InsertBuildStages([])


def GetTestDataSeries(test_data_path):
  """Get metadata from json files at |test_data_path|.

  Returns:
    A list of CBuildbotMetadata objects, sorted by their start time.
  """
  filenames = glob.glob(os.path.join(test_data_path, '*.json'))
  metadatas = []
  for fn in filenames:
    with open(fn, 'r') as f:
      metadatas.append(
          metadata_lib.CBuildbotMetadata.FromJSONString(f.read()))

  # Convert start time values, which are stored in RFC 2822 string format,
  # to seconds since epoch.
  timestamp_from_dict = lambda x: cros_build_lib.ParseUserDateTimeFormat(
      x.GetDict()['time']['start'])

  metadatas.sort(key=timestamp_from_dict)
  return metadatas


class DataSeries0Test(CIDBIntegrationTest):
  """Simulate a set of 630 master/slave CQ builds."""

  def runTest(self):
    """Simulate a set of 630 master/slave CQ builds, with database schema v4.

    Note: This test takes about 2.5 minutes to populate its 630 builds
    and their corresponding cl actions into the test database.
    """
    metadatas = GetTestDataSeries(SERIES_0_TEST_DATA_PATH)
    self.assertEqual(len(metadatas), 630, 'Did not load expected amount of '
                                          'test data')

    # Migrate db to specified version. As new schema versions are added,
    # migrations to later version can be applied after the test builds are
    # simulated, to test that db contents are correctly migrated.
    self._PrepareFreshDatabase(5)

    bot_db = cidb.CIDBConnection(TEST_DB_CRED_BOT)

    # Simulate the test builds, using a database connection as the
    # bot user.
    self.simulate_builds(bot_db, metadatas)

    # Perform some sanity check queries against the database, connected
    # as the readonly user.
    readonly_db = cidb.CIDBConnection(TEST_DB_CRED_READONLY)

    # Sanity checks that correct data was recorded, and can be retrieved.
    max_start_time = readonly_db._GetEngine().execute(
        'select max(start_time) from buildTable').fetchall()[0][0]
    min_start_time = readonly_db._GetEngine().execute(
        'select min(start_time) from buildTable').fetchall()[0][0]
    max_fin_time = readonly_db._GetEngine().execute(
          'select max(finish_time) from buildTable').fetchall()[0][0]
    min_fin_time = readonly_db._GetEngine().execute(
          'select min(finish_time) from buildTable').fetchall()[0][0]
    self.assertEqual(max_start_time, datetime.datetime(2014, 7, 7, 12, 49, 44))
    self.assertEqual(min_start_time, datetime.datetime(2014, 7, 4, 16, 14, 28))
    self.assertEqual(max_fin_time, datetime.datetime(2014, 7, 7, 14, 51, 38))
    self.assertEqual(min_fin_time, datetime.datetime(2014, 7, 4, 16, 33, 10))

    build_types = readonly_db._GetEngine().execute(
        'select build_type from buildTable').fetchall()
    self.assertTrue(all(x == ('paladin',) for x in build_types))

    build_config_count = readonly_db._GetEngine().execute(
        'select COUNT(distinct build_config) from buildTable').fetchall()[0][0]
    self.assertEqual(build_config_count, 30)

    submitted_cl_count = readonly_db._GetEngine().execute(
        'select count(*) from clActionTable where action="submitted"'
        ).fetchall()[0][0]
    rejected_cl_count = readonly_db._GetEngine().execute(
        'select count(*) from clActionTable where action="kicked_out"'
        ).fetchall()[0][0]
    total_actions = readonly_db._GetEngine().execute(
        'select count(*) from clActionTable').fetchall()[0][0]
    self.assertEqual(submitted_cl_count, 56)
    self.assertEqual(rejected_cl_count, 8)
    self.assertEqual(total_actions, 1877)

  def simulate_builds(self, db, metadatas):
    """Simulate a serires of Commit Queue master and slave builds.

    This method use the metadata objects in |metadatas| to simulate those
    builds insertions and updates to the cidb. All metadatas encountered
    after a particular master build will be assumed to be slaves of that build,
    until a new master build is encountered. Slave builds for a particular
    master will be simulated in parallel.

    The first element in |metadatas| must be a CQ master build.

    Args:
      db: A CIDBConnection instance.
      metadatas: A list of CBuildbotMetadata instances, sorted by start time.
    """
    m_iter = iter(metadatas)

    def is_master(m):
      return m.GetDict()['bot-config'] == 'master-paladin'

    next_master = m_iter.next()

    while next_master:
      master = next_master
      next_master = None
      assert is_master(master)
      master_build_id = SimulateCQBuildStart(db, master)

      def simulate_slave(slave_metadata):
        build_id = SimulateCQBuildStart(db, slave_metadata,
                                        master_build_id)
        SimulateCQBuildFinish(db, slave_metadata, build_id)
        logging.debug('Simulated slave build %s on pid %s', build_id,
                      os.getpid())
        return build_id

      slave_metadatas = []
      for slave in m_iter:
        if is_master(slave):
          next_master = slave
          break
        slave_metadatas.append(slave)

      with parallel.BackgroundTaskRunner(simulate_slave, processes=15) as queue:
        for slave in slave_metadatas:
          queue.put([slave])

      SimulateCQBuildFinish(db, master, master_build_id)
      logging.debug('Simulated master build %s', master_build_id)


def _TranslateStatus(status):
  # TODO(akeshet): The status strings used in BuildStatus are not the same as
  # those recorded in CBuildbotMetadata. Use a general purpose adapter.
  if status == 'passed':
    return 'pass'

  if status == 'failed':
    return 'fail'

  return status


def SimulateCQBuildStart(db, metadata, master_build_id=None):
  """Returns (build_id, metadata_id) tuple."""
  metadata_dict = metadata.GetDict()
  # TODO(akeshet): We are pretending that all these builds were on the internal
  # waterfall at the moment, for testing purposes. This is because we don't
  # actually save in the metadata.json any way to know which waterfall the
  # build was on.
  waterfall = 'chromeos'

  start_time = cros_build_lib.ParseUserDateTimeFormat(
      metadata_dict['time']['start'])

  build_id = db.InsertBuild(metadata_dict['builder-name'],
                            waterfall,
                            metadata_dict['build-number'],
                            metadata_dict['bot-config'],
                            metadata_dict['bot-hostname'],
                            start_time,
                            master_build_id)

  return build_id


def SimulateCQBuildFinish(db, metadata, build_id):

  metadata_dict = metadata.GetDict()

  # Insert the first build stage using InsertBuildStage, then batch-insert
  # the rest with InsertBuildStages. This allows us to test InsertBuildStage
  # without taking too much performance loss in the test.
  stage_results = metadata_dict['results']
  if len(stage_results) > 0:
    r = stage_results[0]
    db.InsertBuildStage(build_id, r['name'], r['board'],
                        _TranslateStatus(r['status']), r['log'],
                        cros_build_lib.ParseDurationToSeconds(r['duration']),
                        r['summary'])
  if len(stage_results) > 1:
    stages = [{'build_id': build_id,
               'name': r['name'],
               'board': r['board'],
               'status': _TranslateStatus(r['status']),
               'log_url': r['log'],
               'duration_seconds':
                 cros_build_lib.ParseDurationToSeconds(r['duration']),
               'summary': r['summary']}
              for r in stage_results[1:]]
    db.InsertBuildStages(stages)

  db.InsertCLActions(build_id, metadata_dict['cl_actions'])

  db.UpdateMetadata(build_id, metadata)

  finish_time = cros_build_lib.ParseUserDateTimeFormat(
      metadata_dict['time']['finish'])
  status = metadata_dict['status']['status']

  status = _TranslateStatus(status)

  db.FinishBuild(build_id, finish_time, status)


# TODO(akeshet): Allow command line args to specify alternate CIDB instance
# for testing.
if __name__ == '__main__':
  logging.root.setLevel(logging.DEBUG)
  logging.root.addHandler(logging.StreamHandler())
  cros_test_lib.main()
