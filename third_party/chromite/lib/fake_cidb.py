# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Fake CIDB for unit testing."""

from __future__ import print_function

import datetime
import itertools

from chromite.cbuildbot import constants
from chromite.lib import clactions


class FakeCIDBConnection(object):
  """Fake connection to a Continuous Integration database.

  This class is a partial re-implementation of CIDBConnection, using
  in-memory lists rather than a backing database.
  """
  def __init__(self):
    self.buildTable = []
    self.clActionTable = []
    self.buildStageTable = {}
    self.fake_time = None

  def SetTime(self, fake_time):
    """Sets a fake time to be retrieved by GetTime.

    Args:
      fake_time: datetime.datetime object.
    """
    self.fake_time = fake_time

  def GetTime(self):
    """Gets the current database time."""
    return self.fake_time or datetime.datetime.now()

  def InsertBuild(self, builder_name, waterfall, build_number,
                  build_config, bot_hostname, master_build_id=None,
                  deadline=None, status=constants.BUILDER_STATUS_PASSED):
    """Insert a build row.

    Note this API slightly differs from cidb as we pass status to avoid having
    to have a later FinishBuild call in testing.
    """
    row = {'builder_name': builder_name,
           'buildbot_generation': constants.BUILDBOT_GENERATION,
           'waterfall': waterfall,
           'build_number': build_number,
           'build_config' : build_config,
           'bot_hostname': bot_hostname,
           'start_time': datetime.datetime.now(),
           'master_build_id' : master_build_id,
           'deadline': deadline,
           'status': status}
    build_id = len(self.buildTable)
    self.buildTable.append(row)
    return build_id

  def InsertCLActions(self, build_id, cl_actions, timestamp=None):
    """Insert a list of |cl_actions|."""
    if not cl_actions:
      return 0

    rows = []
    for cl_action in cl_actions:
      change_number = int(cl_action.change_number)
      patch_number = int(cl_action.patch_number)
      change_source = cl_action.change_source
      action = cl_action.action
      reason = cl_action.reason
      rows.append({
          'build_id' : build_id,
          'change_source' : change_source,
          'change_number': change_number,
          'patch_number' : patch_number,
          'action' : action,
          'timestamp': timestamp or datetime.datetime.now(),
          'reason' : reason})

    self.clActionTable.extend(rows)
    return len(rows)

  def InsertBuildStage(self, build_id, name, board=None,
                       status=constants.BUILDER_STATUS_PLANNED):
    build_stage_id = len(self.buildStageTable)
    row = {'build_id': build_id,
           'name': name,
           'board': board,
           'status': status}
    self.buildStageTable[build_stage_id] = row
    return build_stage_id

  def StartBuildStage(self, build_stage_id):
    if build_stage_id > len(self.buildStageTable):
      return

    self.buildStageTable[build_stage_id]['status'] = (
        constants.BUILDER_STATUS_INFLIGHT)

  def ExtendDeadline(self, build_id, timeout):
    # No sanity checking in fake object.
    self.buildStageTable[build_id]['deadline'] = timeout

  def FinishBuildStage(self, build_stage_id, status):
    if build_stage_id > len(self.buildStageTable):
      return

    self.buildStageTable[build_stage_id]['status'] = status

  def GetActionsForChanges(self, changes):
    """Gets all the actions for the given changes."""
    clauses = set()
    for change in changes:
      change_source = 'internal' if change.internal else 'external'
      clauses.add((int(change.gerrit_number), change_source))
    values = []
    for row in self.GetActionHistory():
      if (row.change_number, row.change_source) in clauses:
        values.append(row)
    return values

  def GetActionHistory(self, *args, **kwargs):
    """Get all the actions for all changes."""
    # pylint: disable=W0613
    values = []
    for item, action_id in zip(self.clActionTable, itertools.count()):
      row = (
          action_id,
          item['build_id'],
          item['action'],
          item['reason'],
          self.buildTable[item['build_id']]['build_config'],
          item['change_number'],
          item['patch_number'],
          item['change_source'],
          item['timestamp'])
      values.append(row)

    return [clactions.CLAction(*row) for row in values]

  def GetBuildStatus(self, build_id):
    """Gets the status of the build."""
    return self.buildTable[build_id - 1]

  def GetBuildStatuses(self, build_ids):
    """Gets the status of the builds."""
    return [self.buildTable[x -1] for x in build_ids]

  def GetLastBuildStatuses(self, build_config, number):
    """Returns the last |number| builds for the given |build_config|."""
    def ReduceToBuildConfig(new_list, current_build):
      """Filters a build list to only those of a given config."""
      if current_build['build_config'] == build_config:
        new_list.append(current_build)

      return new_list

    build_configs = reduce(ReduceToBuildConfig, self.buildTable, [])
    # Reverse sort as that's what's expected.
    return sorted(build_configs[-number:], reverse=True)
