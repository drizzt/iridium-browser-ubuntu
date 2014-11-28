#!/usr/bin/env python
# Copyright 2013 The Swarming Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0 that
# can be found in the LICENSE file.

import datetime
import getpass
import hashlib
import inspect
import json
import logging
import os
import shutil
import StringIO
import sys
import tempfile
import threading
import unittest

# net_utils adjusts sys.path.
import net_utils

from depot_tools import auto_stub

import swarming
import test_utils

from utils import net
from utils import zip_package


ALGO = hashlib.sha1
FILE_NAME = u'test.isolated'
FILE_HASH = u'1' * 40
TEST_NAME = u'unit_tests'


TEST_CASE_SUCCESS = (
  '[----------] 2 tests from StaticCookiePolicyTest\n'
  '[ RUN      ] StaticCookiePolicyTest.AllowAllCookiesTest\n'
  '[       OK ] StaticCookiePolicyTest.AllowAllCookiesTest (0 ms)\n'
  '[ RUN      ] StaticCookiePolicyTest.BlockAllCookiesTest\n'
  '[       OK ] StaticCookiePolicyTest.BlockAllCookiesTest (0 ms)\n'
  '[----------] 2 tests from StaticCookiePolicyTest (0 ms total)\n'
  '\n'
  '[----------] 1 test from TCPListenSocketTest\n'
  '[ RUN      ] TCPListenSocketTest.ServerSend\n'
  '[       OK ] TCPListenSocketTest.ServerSend (1 ms)\n'
  '[----------] 1 test from TCPListenSocketTest (1 ms total)\n')


TEST_CASE_FAILURE = (
  '[----------] 2 tests from StaticCookiePolicyTest\n'
  '[ RUN      ] StaticCookiePolicyTest.AllowAllCookiesTest\n'
  '[       OK ] StaticCookiePolicyTest.AllowAllCookiesTest (0 ms)\n'
  '[ RUN      ] StaticCookiePolicyTest.BlockAllCookiesTest\n'
  'C:\\win\\build\\src\\chrome\\test.cc: error: Value of: result()\n'
  '  Actual: false\n'
  'Expected: true\n'
  '[  FAILED  ] StaticCookiePolicyTest.BlockAllCookiesTest (0 ms)\n'
  '[----------] 2 tests from StaticCookiePolicyTest (0 ms total)\n'
  '\n'
  '[----------] 1 test from TCPListenSocketTest\n'
  '[ RUN      ] TCPListenSocketTest.ServerSend\n'
  '[       OK ] TCPListenSocketTest.ServerSend (1 ms)\n'
  '[----------] 1 test from TCPListenSocketTest (1 ms total)\n')


SWARM_OUTPUT_SUCCESS = (
  '[ RUN      ] unittests.Run Test\n' +
  TEST_CASE_SUCCESS +
  '[       OK ] unittests.Run Test (2549 ms)\n'
  '[ RUN      ] unittests.Clean Up\n'
  'No output!\n'
  '[       OK ] unittests.Clean Up (6 ms)\n'
  '\n'
  '[----------] unittests summary\n'
  '[==========] 2 tests ran. (2556 ms total)\n')


SWARM_OUTPUT_FAILURE = (
  '[ RUN      ] unittests.Run Test\n' +
  TEST_CASE_FAILURE +
  '[       OK ] unittests.Run Test (2549 ms)\n'
  '[ RUN      ] unittests.Clean Up\n'
  'No output!\n'
  '[       OK ] unittests.Clean Up (6 ms)\n'
  '\n'
  '[----------] unittests summary\n'
  '[==========] 2 tests ran. (2556 ms total)\n')


SWARM_OUTPUT_WITH_NO_TEST_OUTPUT = (
  '\n'
  'Unable to connection to swarm machine.\n')


TEST_SHARD_1 = 'Note: This is test shard 1 of 3.'
TEST_SHARD_2 = 'Note: This is test shard 2 of 3.'
TEST_SHARD_3 = 'Note: This is test shard 3 of 3.'


SWARM_SHARD_OUTPUT = (
  '[ RUN      ] unittests.Run Test\n'
  '%s\n'
  '[       OK ] unittests.Run Test (2549 ms)\n'
  '[ RUN      ] unittests.Clean Up\n'
  'No output!\n'
  '[       OK ] unittests.Clean Up (6 ms)\n'
  '\n'
  '[----------] unittests summary\n'
  '[==========] 2 tests ran. (2556 ms total)\n')


TEST_SHARD_OUTPUT_1 = SWARM_SHARD_OUTPUT % TEST_SHARD_1
TEST_SHARD_OUTPUT_2 = SWARM_SHARD_OUTPUT % TEST_SHARD_2
TEST_SHARD_OUTPUT_3 = SWARM_SHARD_OUTPUT % TEST_SHARD_3

FAKE_BUNDLE_URL = 'http://localhost:8081/fetch_url'


def gen_data(shard_output, exit_codes):
  return {
    u'config_instance_index': 0,
    u'exit_codes': unicode(exit_codes),
    u'machine_id': u'host',
    u'machine_tag': u'localhost',
    u'output': unicode(shard_output),
    u'isolated_out': swarming.extract_output_files_location(shard_output),
  }


def gen_yielded_data(index, shard_output, exit_codes):
  """Returns an entry as it would be yielded by yield_results()."""
  return index, gen_data(shard_output, exit_codes)


def generate_url_response(shard_output, exit_codes):
  return json.dumps(gen_data(shard_output, exit_codes))


def get_swarm_results(keys, output_collector=None):
  """Simplifies the call to yield_results().

  The timeout is hard-coded to 10 seconds.
  """
  return list(
      swarming.yield_results(
          'http://host:9001', keys, 10., None, True, output_collector))


def collect(url, task_name, shards):
  """Simplifies the call to swarming.collect()."""
  return swarming.collect(
    url=url,
    task_name=task_name,
    shards=shards,
    timeout=10,
    decorate=True,
    print_status_updates=True,
    task_summary_json=None,
    task_output_dir=None)


def gen_trigger_response(priority=101):
  # As seen in services/swarming/handlers_frontend.py.
  return {
    'priority': priority,
    'test_case_name': 'foo',
    'test_keys': [
      {
        'config_name': 'foo',
        'instance_index': 0,
        'num_instances': 1,
        'test_key': '123',
      }
    ],
  }


def main(args):
  """Bypassies swarming.main()'s exception handling.

  It gets in the way when debugging test failures.
  """
  dispatcher = swarming.subcommand.CommandDispatcher('swarming')
  return dispatcher.execute(swarming.OptionParserSwarming(), args)


# Silence pylint 'Access to a protected member _Event of a client class'.
class NonBlockingEvent(threading._Event):  # pylint: disable=W0212
  """Just like threading.Event, but a class and ignores timeout in 'wait'.

  Intended to be used as a mock for threading.Event in tests.
  """

  def wait(self, timeout=None):
    return super(NonBlockingEvent, self).wait(0)


class TestCase(net_utils.TestCase):
  """Base class that defines the url_open mock."""
  def setUp(self):
    super(TestCase, self).setUp()
    self._lock = threading.Lock()
    self.mock(swarming.auth, 'ensure_logged_in', lambda _: None)
    self.mock(swarming.time, 'sleep', lambda _: None)
    self.mock(swarming.subprocess, 'call', lambda *_: self.fail())
    self.mock(swarming.threading, 'Event', NonBlockingEvent)
    self.mock(sys, 'stdout', StringIO.StringIO())
    self.mock(sys, 'stderr', StringIO.StringIO())

  def tearDown(self):
    try:
      if not self.has_failed():
        self._check_output('', '')
    finally:
      super(TestCase, self).tearDown()

  def _check_output(self, out, err):
    self.assertEqual(out, sys.stdout.getvalue())
    self.assertEqual(err, sys.stderr.getvalue())

    # Flush their content by mocking them again.
    self.mock(sys, 'stdout', StringIO.StringIO())
    self.mock(sys, 'stderr', StringIO.StringIO())


class TestGetTestKeys(TestCase):
  def test_no_keys(self):
    self.mock(swarming.time, 'sleep', lambda x: x)
    self.expected_requests(
        [
          (
            'http://host:9001/get_matching_test_cases?name=my_test',
            {'retry_404': True},
            'No matching Test Cases',
            None,
          ) for _ in range(net.URL_OPEN_MAX_ATTEMPTS)
        ])
    try:
      swarming.get_task_keys('http://host:9001', 'my_test')
      self.fail()
    except swarming.Failure as e:
      msg = (
          'Error: Unable to find any task with the name, my_test, on swarming '
          'server')
      self.assertEqual(msg, e.args[0])

  def test_no_keys_on_first_attempt(self):
    self.mock(swarming.time, 'sleep', lambda x: x)
    keys = ['key_1', 'key_2']
    self.expected_requests(
        [
          (
            'http://host:9001/get_matching_test_cases?name=my_test',
            {'retry_404': True},
            'No matching Test Cases',
            None,
          ),
          (
            'http://host:9001/get_matching_test_cases?name=my_test',
            {'retry_404': True},
            json.dumps(keys),
            None,
          ),
        ])
    actual = swarming.get_task_keys('http://host:9001', 'my_test')
    self.assertEqual(keys, actual)

  def test_find_keys(self):
    keys = ['key_1', 'key_2']
    self.expected_requests(
        [
          (
            'http://host:9001/get_matching_test_cases?name=my_test',
            {'retry_404': True},
            json.dumps(keys),
            None,
          ),
        ])
    actual = swarming.get_task_keys('http://host:9001', 'my_test')
    self.assertEqual(keys, actual)


class TestGetSwarmResults(TestCase):
  def test_success(self):
    self.expected_requests(
        [
          (
            'http://host:9001/get_result?r=key1',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(SWARM_OUTPUT_SUCCESS, '0, 0'),
            None,
          ),
        ])
    expected = [gen_yielded_data(0, SWARM_OUTPUT_SUCCESS, '0, 0')]
    actual = get_swarm_results(['key1'])
    self.assertEqual(expected, actual)

  def test_failure(self):
    self.expected_requests(
        [
          (
            'http://host:9001/get_result?r=key1',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(SWARM_OUTPUT_FAILURE, '0, 1'),
            None,
          ),
        ])
    expected = [gen_yielded_data(0, SWARM_OUTPUT_FAILURE, '0, 1')]
    actual = get_swarm_results(['key1'])
    self.assertEqual(expected, actual)

  def test_no_test_output(self):
    self.expected_requests(
        [
          (
            'http://host:9001/get_result?r=key1',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(SWARM_OUTPUT_WITH_NO_TEST_OUTPUT, '0, 0'),
            None,
          ),
        ])
    expected = [gen_yielded_data(0, SWARM_OUTPUT_WITH_NO_TEST_OUTPUT, '0, 0')]
    actual = get_swarm_results(['key1'])
    self.assertEqual(expected, actual)

  def test_no_keys(self):
    actual = get_swarm_results([])
    self.assertEqual([], actual)

  def test_url_errors(self):
    self.mock(logging, 'error', lambda *_, **__: None)
    # NOTE: get_swarm_results() hardcodes timeout=10.
    now = {}
    lock = threading.Lock()
    def get_now():
      t = threading.current_thread()
      with lock:
        return now.setdefault(t, range(10)).pop(0)
    self.mock(swarming.net, 'sleep_before_retry', lambda _x, _y: None)
    self.mock(swarming, 'now', get_now)
    # The actual number of requests here depends on 'now' progressing to 10
    # seconds. It's called once per loop. Loop makes 9 iterations.
    self.expected_requests(
        9 * [
          (
            'http://host:9001/get_result?r=key1',
            {'retry_404': False, 'retry_50x': False},
            None,
            None,
          )
        ])
    actual = get_swarm_results(['key1'])
    self.assertEqual([], actual)
    self.assertTrue(all(not v for v in now.itervalues()), now)

  def test_many_shards(self):
    self.expected_requests(
        [
          (
            'http://host:9001/get_result?r=key1',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(TEST_SHARD_OUTPUT_1, '0, 0'),
            None,
          ),
          (
            'http://host:9001/get_result?r=key2',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(TEST_SHARD_OUTPUT_2, '0, 0'),
            None,
          ),
          (
            'http://host:9001/get_result?r=key3',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(TEST_SHARD_OUTPUT_3, '0, 0'),
            None,
          ),
        ])
    expected = [
      gen_yielded_data(0, TEST_SHARD_OUTPUT_1, '0, 0'),
      gen_yielded_data(1, TEST_SHARD_OUTPUT_2, '0, 0'),
      gen_yielded_data(2, TEST_SHARD_OUTPUT_3, '0, 0'),
    ]
    actual = get_swarm_results(['key1', 'key2', 'key3'])
    self.assertEqual(expected, sorted(actual))

  def test_output_collector_called(self):
    # Three shards, one failed. All results are passed to output collector.
    self.expected_requests(
        [
          (
            'http://host:9001/get_result?r=key1',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(TEST_SHARD_OUTPUT_1, '0, 0'),
            None,
          ),
          (
            'http://host:9001/get_result?r=key2',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(TEST_SHARD_OUTPUT_2, '0, 0'),
            None,
          ),
          (
            'http://host:9001/get_result?r=key3',
            {'retry_404': False, 'retry_50x': False},
            generate_url_response(SWARM_OUTPUT_FAILURE, '0, 1'),
            None,
          ),
        ])

    class FakeOutputCollector(object):
      def __init__(self):
        self.results = []
        self._lock = threading.Lock()

      def process_shard_result(self, index, result):
        with self._lock:
          self.results.append((index, result))

    output_collector = FakeOutputCollector()
    get_swarm_results(['key1', 'key2', 'key3'], output_collector)

    expected = [
      (0, gen_data(TEST_SHARD_OUTPUT_1, '0, 0')),
      (1, gen_data(TEST_SHARD_OUTPUT_2, '0, 0')),
      (2, gen_data(SWARM_OUTPUT_FAILURE, '0, 1')),
    ]
    self.assertEqual(sorted(expected), sorted(output_collector.results))

  def test_collect_nothing(self):
    self.mock(swarming, 'get_task_keys', lambda *_: ['task_key'])
    self.mock(swarming, 'yield_results', lambda *_: [])
    self.assertEqual(1, collect('url', 'name', 2))
    self._check_output('', 'Results from some shards are missing: 0, 1\n')

  def test_collect_success(self):
    self.mock(swarming, 'get_task_keys', lambda *_: ['task_key'])
    data = {
      'config_instance_index': 0,
      'exit_codes': '0',
      'machine_id': 0,
      'output': 'Foo\n',
    }
    self.mock(swarming, 'yield_results', lambda *_: [(0, data)])
    self.assertEqual(0, collect('url', 'name', 1))
    self._check_output(
        '\n================================================================\n'
        'Begin output from shard index 0 (machine tag: 0, id: unknown)\n'
        '================================================================\n\n'
        'Foo\n'
        '================================================================\n'
        'End output from shard index 0 (machine tag: 0, id: unknown).\n'
        'Exit code 0 (0x0).\n'
        '================================================================\n\n',
        '')

  def test_collect_fail(self):
    self.mock(swarming, 'get_task_keys', lambda *_: ['task_key'])
    data = {
      'config_instance_index': 0,
      'exit_codes': '0,8',
      'machine_id': 0,
      'output': 'Foo\n',
    }
    self.mock(swarming, 'yield_results', lambda *_: [(0, data)])
    self.assertEqual(1, collect('url', 'name', 1))
    self._check_output(
        '\n================================================================\n'
        'Begin output from shard index 0 (machine tag: 0, id: unknown)\n'
        '================================================================\n\n'
        'Foo\n'
        '================================================================\n'
        'End output from shard index 0 (machine tag: 0, id: unknown).\n'
        'Exit code 8 (0x8).\n'
        '================================================================\n\n',
        '')

  def test_collect_negative_exit_code(self):
    self.mock(swarming, 'get_task_keys', lambda *_: ['task_key'])
    data = {
      'config_instance_index': 0,
      'exit_codes': '-1073741515,0',
      'machine_id': 0,
      'output': 'Foo\n',
    }
    self.mock(swarming, 'yield_results', lambda *_: [(0, data)])
    self.assertEqual(1, collect('url', 'name', 1))
    self._check_output(
        '\n================================================================\n'
        'Begin output from shard index 0 (machine tag: 0, id: unknown)\n'
        '================================================================\n\n'
        'Foo\n'
        '================================================================\n'
        'End output from shard index 0 (machine tag: 0, id: unknown).\n'
        'Exit code -1073741515 (0xc0000135).\n'
        '================================================================\n\n',
        '')

  def test_collect_one_missing(self):
    self.mock(swarming, 'get_task_keys', lambda *_: ['task_key'])
    data = {
      'config_instance_index': 0,
      'exit_codes': '0',
      'machine_id': 0,
      'output': 'Foo\n',
    }
    self.mock(swarming, 'yield_results', lambda *_: [(0, data)])
    self.assertEqual(1, collect('url', 'name', 2))
    self._check_output(
        '\n================================================================\n'
        'Begin output from shard index 0 (machine tag: 0, id: unknown)\n'
        '================================================================\n\n'
        'Foo\n'
        '================================================================\n'
        'End output from shard index 0 (machine tag: 0, id: unknown).\n'
        'Exit code 0 (0x0).\n'
        '================================================================\n\n',
        'Results from some shards are missing: 1\n')


def chromium_tasks(retrieval_url, file_hash, extra_args):
  return [
    {
      u'action': [
        u'python', u'run_isolated.zip',
        u'--hash', file_hash,
        u'--namespace', u'default-gzip',
        u'--isolate-server', retrieval_url,
      ] + (['--'] + list(extra_args) if extra_args else []),
      u'decorate_output': False,
      u'test_name': u'Run Test',
      u'hard_time_out': 2*60*60,
    },
    {
      u'action' : [
          u'python', u'swarm_cleanup.py',
      ],
      u'decorate_output': False,
      u'test_name': u'Clean Up',
      u'hard_time_out': 2*60*60,
    }
  ]


def generate_expected_json(
    shards,
    shard_index,
    dimensions,
    env,
    isolate_server,
    profile,
    test_case_name=TEST_NAME,
    file_hash=FILE_HASH,
    extra_args=None):
  expected = {
    u'cleanup': u'root',
    u'configurations': [
      {
        u'config_name': u'isolated',
        u'deadline_to_run': 60*60,
        u'dimensions': dimensions,
        u'priority': 101,
      },
    ],
    u'data': [],
    u'env_vars': env.copy(),
    u'test_case_name': test_case_name,
    u'tests': chromium_tasks(isolate_server, file_hash, extra_args),
  }
  if shards > 1:
    expected[u'env_vars'][u'GTEST_SHARD_INDEX'] = u'%d' % shard_index
    expected[u'env_vars'][u'GTEST_TOTAL_SHARDS'] = u'%d' % shards
  if profile:
    expected[u'tests'][0][u'action'].append(u'--verbose')
  return expected


class MockedStorage(object):
  def __init__(self, warm_cache):
    self._warm_cache = warm_cache

  def __enter__(self):
    return self

  def __exit__(self, *_args):
    pass

  def upload_items(self, items):
    return [] if self._warm_cache else items

  def get_fetch_url(self, _item):  # pylint: disable=R0201
    return FAKE_BUNDLE_URL


class TriggerTaskShardsTest(TestCase):
  def test_zip_bundle_files(self):
    manifest = swarming.Manifest(
        isolate_server='http://localhost:8081',
        namespace='default-gzip',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=None,
        env={},
        dimensions={'os': 'Linux'},
        deadline=60*60,
        verbose=False,
        profile=False,
        priority=101)

    bundle = zip_package.ZipPackage(swarming.ROOT_DIR)
    swarming.setup_run_isolated(manifest, bundle)

    self.assertEqual(
        set(['run_isolated.zip', 'swarm_cleanup.py']), set(bundle.files))

  def test_basic(self):
    manifest = swarming.Manifest(
        isolate_server='http://localhost:8081',
        namespace='default-gzip',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=None,
        env={},
        dimensions={'os': 'Linux'},
        deadline=60*60,
        verbose=False,
        profile=False,
        priority=101)

    swarming.setup_run_isolated(manifest, None)
    manifest_json = json.loads(manifest.to_json())

    expected = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={u'os': u'Linux'},
        env={},
        isolate_server=u'http://localhost:8081',
        profile=False)
    self.assertEqual(expected, manifest_json)

  def test_basic_profile(self):
    manifest = swarming.Manifest(
        isolate_server='http://localhost:8081',
        namespace='default-gzip',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=None,
        env={},
        dimensions={'os': 'Linux'},
        deadline=60*60,
        verbose=False,
        profile=True,
        priority=101)

    swarming.setup_run_isolated(manifest, None)
    manifest_json = json.loads(manifest.to_json())

    expected = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={u'os': u'Linux'},
        env={},
        isolate_server=u'http://localhost:8081',
        profile=True)
    self.assertEqual(expected, manifest_json)

  def test_manifest_with_extra_args(self):
    manifest = swarming.Manifest(
        isolate_server='http://localhost:8081',
        namespace='default-gzip',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=['--extra-cmd-arg=1234', 'some more'],
        env={},
        dimensions={'os': 'Windows'},
        deadline=60*60,
        verbose=False,
        profile=False,
        priority=101)

    swarming.setup_run_isolated(manifest, None)
    manifest_json = json.loads(manifest.to_json())

    expected = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={u'os': u'Windows'},
        env={},
        isolate_server=u'http://localhost:8081',
        profile=False,
        extra_args=['--extra-cmd-arg=1234', 'some more'])
    self.assertEqual(expected, manifest_json)

  def test_manifest_for_shard(self):
    manifest = swarming.Manifest(
        isolate_server='http://localhost:8081',
        namespace='default-gzip',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=None,
        env=swarming.setup_googletest({}, 5, 3),
        dimensions={'os': 'Linux'},
        deadline=60*60,
        verbose=False,
        profile=False,
        priority=101)

    swarming.setup_run_isolated(manifest, None)
    manifest_json = json.loads(manifest.to_json())

    expected = generate_expected_json(
        shards=5,
        shard_index=3,
        dimensions={u'os': u'Linux'},
        env={},
        isolate_server=u'http://localhost:8081',
        profile=False)
    self.assertEqual(expected, manifest_json)

  def test_trigger_task_shards_success(self):
    self.mock(
        swarming.net, 'url_read',
        lambda url, data=None: json.dumps(gen_trigger_response()))
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=False))

    tasks = swarming.trigger_task_shards(
        swarming='http://localhost:8082',
        isolate_server='http://localhost:8081',
        namespace='default',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=['--some-arg', '123'],
        shards=1,
        dimensions={},
        env={},
        deadline=60*60,
        verbose=False,
        profile=False,
        priority=101)
    expected = {
      'unit_tests': {
        'shard_index': 0,
        'task_id': '123',
        'view_url': 'http://localhost:8082/user/task/123',
      }
    }
    self.assertEqual(expected, tasks)

  def test_trigger_task_shards_priority_override(self):
    self.mock(
        swarming.net, 'url_read',
        lambda url, data=None: json.dumps(gen_trigger_response(priority=200)))
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=False))

    tasks = swarming.trigger_task_shards(
        swarming='http://localhost:8082',
        isolate_server='http://localhost:8081',
        namespace='default',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=['--some-arg', '123'],
        shards=2,
        dimensions={},
        env={},
        deadline=60*60,
        verbose=False,
        profile=False,
        priority=101)
    expected = {
      u'unit_tests:2:0': {
        u'shard_index': 0,
        u'task_id': u'123',
        u'view_url': u'http://localhost:8082/user/task/123',
      },
      u'unit_tests:2:1': {
        u'shard_index': 1,
        u'task_id': u'123',
        u'view_url': u'http://localhost:8082/user/task/123',
      }
    }
    self.assertEqual(expected, tasks)
    self._check_output('', 'Priority was reset to 200\n')

  def test_trigger_task_shards_success_zip_already_uploaded(self):
    self.mock(
        swarming.net, 'url_read',
        lambda url, data=None: json.dumps(gen_trigger_response()))
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=True))

    dimensions = {'os': 'linux2'}
    tasks = swarming.trigger_task_shards(
        swarming='http://localhost:8082',
        isolate_server='http://localhost:8081',
        namespace='default',
        isolated_hash=FILE_HASH,
        task_name=TEST_NAME,
        extra_args=['--some-arg', '123'],
        shards=1,
        dimensions=dimensions,
        env={},
        deadline=60*60,
        verbose=False,
        profile=False,
        priority=101)

    expected = {
      'unit_tests': {
        'shard_index': 0,
        'task_id': '123',
        'view_url': 'http://localhost:8082/user/task/123',
      }
    }
    self.assertEqual(expected, tasks)

  def test_isolated_to_hash(self):
    calls = []
    self.mock(swarming.subprocess, 'call', lambda *c: calls.append(c))
    content = '{}'
    expected_hash = hashlib.sha1(content).hexdigest()
    handle, isolated = tempfile.mkstemp(
        prefix='swarming_test_', suffix='.isolated')
    os.close(handle)
    try:
      with open(isolated, 'w') as f:
        f.write(content)
      hash_value, is_file = swarming.isolated_to_hash(
          'http://localhost:1', 'default', isolated, hashlib.sha1, False)
    finally:
      os.remove(isolated)
    self.assertEqual(expected_hash, hash_value)
    self.assertEqual(True, is_file)
    expected_calls = [
        (
          [
            sys.executable,
            os.path.join(swarming.ROOT_DIR, 'isolate.py'),
            'archive',
            '--isolate-server', 'http://localhost:1',
            '--namespace', 'default',
            '--isolated',
            isolated,
          ],
          False,
        ),
    ]
    self.assertEqual(expected_calls, calls)
    self._check_output('Archiving: %s\n' % isolated, '')


class MainTest(TestCase):
  def setUp(self):
    super(MainTest, self).setUp()
    self._tmpdir = None

  def tearDown(self):
    try:
      if self._tmpdir:
        shutil.rmtree(self._tmpdir)
    finally:
      super(MainTest, self).tearDown()

  @property
  def tmpdir(self):
    if not self._tmpdir:
      self._tmpdir = tempfile.mkdtemp(prefix='swarming')
    return self._tmpdir

  def test_run_hash(self):
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=False))
    self.mock(swarming, 'now', lambda: 123456)

    task_name = (
        '%s/foo=bar_os=Mac/1111111111111111111111111111111111111111/123456000' %
        getpass.getuser())
    j = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={'foo': 'bar', 'os': 'Mac'},
        env={},
        isolate_server='https://host2',
        profile=False,
        test_case_name=task_name)
    j['data'] = [[FAKE_BUNDLE_URL, 'swarm_data.zip']]
    data = {
      'request': json.dumps(j, sort_keys=True, separators=(',',':')),
    }
    self.expected_requests(
        [
          (
            'https://host1/test',
            {'data': data},
            json.dumps(gen_trigger_response()),
            None,
          ),
        ])
    ret = main([
        'trigger',
        '--swarming', 'https://host1',
        '--isolate-server', 'https://host2',
        '--shards', '1',
        '--priority', '101',
        '--dimension', 'foo', 'bar',
        '--dimension', 'os', 'Mac',
        '--deadline', '3600',
        FILE_HASH,
      ])
    actual = sys.stdout.getvalue()
    self.assertEqual(0, ret, (actual, sys.stderr.getvalue()))
    self._check_output('Triggered task: %s\n' % task_name, '')

  def test_run_isolated(self):
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=False))
    calls = []
    self.mock(swarming.subprocess, 'call', lambda *c: calls.append(c))
    self.mock(swarming, 'now', lambda: 123456)

    isolated = os.path.join(self.tmpdir, 'zaz.isolated')
    content = '{}'
    with open(isolated, 'wb') as f:
      f.write(content)

    isolated_hash = ALGO(content).hexdigest()
    task_name = 'zaz/foo=bar_os=Mac/%s/123456000' % isolated_hash
    j = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={'foo': 'bar', 'os': 'Mac'},
        env={},
        isolate_server='https://host2',
        profile=False,
        test_case_name=task_name,
        file_hash=isolated_hash)
    j['data'] = [[FAKE_BUNDLE_URL, 'swarm_data.zip']]
    data = {
      'request': json.dumps(j, sort_keys=True, separators=(',',':')),
    }
    self.expected_requests(
        [
          (
            'https://host1/test',
            {'data': data},
            json.dumps(gen_trigger_response()),
            None,
          ),
        ])
    ret = main([
        'trigger',
        '--swarming', 'https://host1',
        '--isolate-server', 'https://host2',
        '--shards', '1',
        '--priority', '101',
        '--dimension', 'foo', 'bar',
        '--dimension', 'os', 'Mac',
        '--deadline', '3600',
        isolated,
      ])
    actual = sys.stdout.getvalue()
    self.assertEqual(0, ret, (actual, sys.stderr.getvalue()))
    expected = [
      (
        [
          sys.executable,
          os.path.join(swarming.ROOT_DIR, 'isolate.py'), 'archive',
          '--isolate-server', 'https://host2',
          '--namespace' ,'default-gzip',
          '--isolated', isolated,
        ],
      0),
    ]
    self.assertEqual(expected, calls)
    self._check_output(
        'Archiving: %s\nTriggered task: %s\n' % (isolated, task_name), '')

  def test_trigger_no_request(self):
    with self.assertRaises(SystemExit):
      main([
            'trigger', '--swarming', 'https://host',
            '--isolate-server', 'https://host', '-T', 'foo',
          ])
    self._check_output(
        '',
        'Usage: swarming.py trigger [options] (hash|isolated) [-- extra_args]'
        '\n\n'
        'swarming.py: error: Must pass one .isolated file or its hash (sha1).'
        '\n')

  def test_trigger_no_env_vars(self):
    with self.assertRaises(SystemExit):
      main(['trigger'])
    self._check_output(
        '',
        'Usage: swarming.py trigger [options] (hash|isolated) [-- extra_args]'
        '\n\n'
        'swarming.py: error: --swarming is required.'
        '\n')

  def test_trigger_no_swarming_env_var(self):
    with self.assertRaises(SystemExit):
      with test_utils.EnvVars({'ISOLATE_SERVER': 'https://host'}):
        main(['trigger', '-T' 'foo', 'foo.isolated'])
    self._check_output(
        '',
        'Usage: swarming.py trigger [options] (hash|isolated) [-- extra_args]'
        '\n\n'
        'swarming.py: error: --swarming is required.'
        '\n')

  def test_trigger_no_isolate_env_var(self):
    with self.assertRaises(SystemExit):
      with test_utils.EnvVars({'SWARMING_SERVER': 'https://host'}):
        main(['trigger', 'T', 'foo', 'foo.isolated'])
    self._check_output(
        '',
        'Usage: swarming.py trigger [options] (hash|isolated) [-- extra_args]'
        '\n\n'
        'swarming.py: error: Use one of --indir or --isolate-server.'
        '\n')

  def test_trigger_env_var(self):
    with self.assertRaises(SystemExit):
      with test_utils.EnvVars({'ISOLATE_SERVER': 'https://host',
                               'SWARMING_SERVER': 'https://host'}):
        main(['trigger', '-T', 'foo'])
    self._check_output(
        '',
        'Usage: swarming.py trigger [options] (hash|isolated) [-- extra_args]'
        '\n\n'
        'swarming.py: error: Must pass one .isolated file or its hash (sha1).'
        '\n')

  def test_trigger_no_task(self):
    with self.assertRaises(SystemExit):
      main([
            'trigger', '--swarming', 'https://host',
            '--isolate-server', 'https://host', 'foo.isolated',
          ])
    self._check_output(
        '',
        'Usage: swarming.py trigger [options] (hash|isolated) [-- extra_args]'
        '\n\n'
        'swarming.py: error: Please at least specify one --dimension\n')

  def test_trigger_env(self):
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=False))
    j = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={'os': 'Mac'},
        env={'foo': 'bar'},
        isolate_server='https://host2',
        profile=False)
    j['data'] = [[FAKE_BUNDLE_URL, 'swarm_data.zip']]
    data = {
      'request': json.dumps(j, sort_keys=True, separators=(',',':')),
    }
    self.expected_requests(
        [
          (
            'https://host1/test',
            {'data': data},
            json.dumps(gen_trigger_response()),
            None,
          ),
        ])
    ret = main([
        'trigger',
        '--swarming', 'https://host1',
        '--isolate-server', 'https://host2',
        '--shards', '1',
        '--priority', '101',
        '--env', 'foo', 'bar',
        '--dimension', 'os', 'Mac',
        '--task-name', TEST_NAME,
        '--deadline', '3600',
        FILE_HASH,
      ])
    actual = sys.stdout.getvalue()
    self.assertEqual(0, ret, (actual, sys.stderr.getvalue()))

  def test_trigger_dimension_filter(self):
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=False))
    j = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={'foo': 'bar', 'os': 'Mac'},
        env={},
        isolate_server='https://host2',
        profile=False)
    j['data'] = [[FAKE_BUNDLE_URL, 'swarm_data.zip']]
    data = {
      'request': json.dumps(j, sort_keys=True, separators=(',',':')),
    }
    self.expected_requests(
        [
          (
            'https://host1/test',
            {'data': data},
            json.dumps(gen_trigger_response()),
            None,
          ),
        ])
    ret = main([
        'trigger',
        '--swarming', 'https://host1',
        '--isolate-server', 'https://host2',
        '--shards', '1',
        '--priority', '101',
        '--dimension', 'foo', 'bar',
        '--dimension', 'os', 'Mac',
        '--task-name', TEST_NAME,
        '--deadline', '3600',
        FILE_HASH,
      ])
    actual = sys.stdout.getvalue()
    self.assertEqual(0, ret, (actual, sys.stderr.getvalue()))

  def test_trigger_dump_json(self):
    called = []
    self.mock(swarming.tools, 'write_json', lambda *args: called.append(args))
    self.mock(swarming.isolateserver, 'get_storage',
        lambda *_: MockedStorage(warm_cache=False))
    j = generate_expected_json(
        shards=1,
        shard_index=0,
        dimensions={'foo': 'bar', 'os': 'Mac'},
        env={},
        isolate_server='https://host2',
        profile=False)
    j['data'] = [[FAKE_BUNDLE_URL, 'swarm_data.zip']]
    data = {
      'request': json.dumps(j, sort_keys=True, separators=(',',':')),
    }
    self.expected_requests(
        [
          (
            'https://host1/test',
            {'data': data},
            json.dumps(gen_trigger_response()),
            None,
          ),
        ])
    ret = main([
        'trigger',
        '--swarming', 'https://host1',
        '--isolate-server', 'https://host2',
        '--shards', '1',
        '--priority', '101',
        '--dimension', 'foo', 'bar',
        '--dimension', 'os', 'Mac',
        '--task-name', TEST_NAME,
        '--deadline', '3600',
        '--dump-json', 'foo.json',
        FILE_HASH,
      ])
    actual = sys.stdout.getvalue()
    self.assertEqual(0, ret, (actual, sys.stderr.getvalue()))
    expected = [
      (
        'foo.json',
        {
          u'base_task_name': u'unit_tests',
          u'tasks': {
            u'unit_tests': {
              u'shard_index': 0,
              u'task_id': u'123',
              u'view_url': u'https://host1/user/task/123',
            }
          },
        },
        True,
      ),
    ]
    self.assertEqual(expected, called)

  def test_query_base(self):
    self.expected_requests(
        [
          (
            'https://localhost:1/swarming/api/v1/client/bots/botid/tasks?'
                'limit=200',
            {},
            {'yo': 'dawg'},
          ),
        ])
    main(
        [
          'query', '--swarming', 'https://localhost:1', 'bots/botid/tasks',
        ])
    self._check_output('{\n  "yo": "dawg"\n}\n', '')

  def test_query_cursor(self):
    self.expected_requests(
        [
          (
            'https://localhost:1/swarming/api/v1/client/bots/botid/tasks?'
                'limit=2',
            {},
            {
              'cursor': '%',
              'extra': False,
              'items': ['A'],
            },
          ),
          (
            'https://localhost:1/swarming/api/v1/client/bots/botid/tasks?'
                'cursor=%25&limit=1',
            {},
            {
              'cursor': None,
              'items': ['B'],
              'ignored': True,
            },
          ),
        ])
    main(
        [
          'query', '--swarming', 'https://localhost:1', 'bots/botid/tasks',
          '--limit', '2',
        ])
    expected = (
        '{\n'
        '  "extra": false, \n'
        '  "items": [\n'
        '    "A", \n'
        '    "B"\n'
        '  ]\n'
        '}\n')
    self._check_output(expected, '')


class BotTestCase(TestCase):
  def setUp(self):
    super(BotTestCase, self).setUp()
    # Expected requests are always the same, independent of the test case.
    self.expected_requests(
        [
          (
            'https://localhost:1/swarming/api/v1/client/bots?limit=250',
            {},
            self.mock_swarming_api_v1_bots_page_1(),
          ),
          (
            'https://localhost:1/swarming/api/v1/client/bots?limit=250&'
              'cursor=opaque_cursor',
            {},
            self.mock_swarming_api_v1_bots_page_2(),
          ),
        ])

  @staticmethod
  def mock_swarming_api_v1_bots_page_1():
    """Returns fake /swarming/api/v1/client/bots data."""
    # Sample data retrieved from actual server.
    now = unicode(datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    return {
      u'items': [
        {
          u'created_ts': now,
          u'dimensions': {
            u'cores': u'4',
            u'cpu': [u'x86', u'x86-64'],
            u'gpu': [u'15ad', u'15ad:0405'],
            u'hostname': u'swarm3.example.com',
            u'id': u'swarm3',
            u'os': [u'Mac', u'Mac-10.9'],
          },
          u'external_ip': u'1.1.1.3',
          u'hostname': u'swarm3.example.com',
          u'id': u'swarm3',
          u'internal_ip': u'192.168.0.3',
          u'is_dead': False,
          u'last_seen_ts': now,
          u'quarantined': False,
          u'task': u'148569b73a89501',
          u'version': u'56918a2ea28a6f51751ad14cc086f118b8727905',
        },
        {
          u'created_ts': now,
          u'dimensions': {
            u'cores': u'8',
            u'cpu': [u'x86', u'x86-64'],
            u'gpu': [],
            u'hostname': u'swarm1.example.com',
            u'id': u'swarm1',
            u'os': [u'Linux', u'Linux-12.04'],
          },
          u'external_ip': u'1.1.1.1',
          u'hostname': u'swarm1.example.com',
          u'id': u'swarm1',
          u'internal_ip': u'192.168.0.1',
          u'is_dead': True,
          u'last_seen_ts': 'A long time ago',
          u'quarantined': False,
          u'task': None,
          u'version': u'56918a2ea28a6f51751ad14cc086f118b8727905',
        },
        {
          u'created_ts': now,
          u'dimensions': {
            u'cores': u'8',
            u'cpu': [u'x86', u'x86-64'],
            u'cygwin': u'0',
            u'gpu': [
              u'15ad',
              u'15ad:0405',
              u'VMware Virtual SVGA 3D Graphics Adapter',
            ],
            u'hostname': u'swarm2.example.com',
            u'id': u'swarm2',
            u'integrity': u'high',
            u'os': [u'Windows', u'Windows-6.1'],
          },
          u'external_ip': u'1.1.1.2',
          u'hostname': u'swarm2.example.com',
          u'id': u'swarm2',
          u'internal_ip': u'192.168.0.2',
          u'is_dead': False,
          u'last_seen_ts': now,
          u'quarantined': False,
          u'task': None,
          u'version': u'56918a2ea28a6f51751ad14cc086f118b8727905',
        },
      ],
      u'cursor': u'opaque_cursor',
      u'death_timeout': 1800.0,
      u'limit': 4,
      u'now': unicode(now),
    }

  @staticmethod
  def mock_swarming_api_v1_bots_page_2():
    """Returns fake /swarming/api/v1/client/bots data."""
    # Sample data retrieved from actual server.
    now = unicode(datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    return {
      u'items': [
        {
          u'created_ts': now,
          u'dimensions': {
            u'cores': u'8',
            u'cpu': [u'x86', u'x86-64'],
            u'gpu': [],
            u'hostname': u'swarm4.example.com',
            u'id': u'swarm4',
            u'os': [u'Linux', u'Linux-12.04'],
          },
          u'external_ip': u'1.1.1.4',
          u'hostname': u'swarm4.example.com',
          u'id': u'swarm4',
          u'internal_ip': u'192.168.0.4',
          u'is_dead': False,
          u'last_seen_ts': now,
          u'quarantined': False,
          u'task': u'14856971a64c601',
          u'version': u'56918a2ea28a6f51751ad14cc086f118b8727905',
        }
      ],
      u'cursor': None,
      u'death_timeout': 1800.0,
      u'limit': 4,
      u'now': unicode(now),
    }

  def test_bots(self):
    main(['bots', '--swarming', 'https://localhost:1'])
    expected = (
        u'swarm2\n'
        u'  {"cores": "8", "cpu": ["x86", "x86-64"], "cygwin": "0", "gpu": '
          '["15ad", "15ad:0405", "VMware Virtual SVGA 3D Graphics Adapter"], '
          '"hostname": "swarm2.example.com", "id": "swarm2", "integrity": '
          '"high", "os": ["Windows", "Windows-6.1"]}\n'
        'swarm3\n'
        '  {"cores": "4", "cpu": ["x86", "x86-64"], "gpu": ["15ad", '
          '"15ad:0405"], "hostname": "swarm3.example.com", "id": "swarm3", '
          '"os": ["Mac", "Mac-10.9"]}\n'
        u'  task: 148569b73a89501\n'
        u'swarm4\n'
        u'  {"cores": "8", "cpu": ["x86", "x86-64"], "gpu": [], "hostname": '
          '"swarm4.example.com", "id": "swarm4", "os": ["Linux", '
          '"Linux-12.04"]}\n'
        u'  task: 14856971a64c601\n')
    self._check_output(expected, '')

  def test_bots_bare(self):
    main(['bots', '--swarming', 'https://localhost:1', '--bare'])
    self._check_output("swarm2\nswarm3\nswarm4\n", '')

  def test_bots_filter(self):
    main(
        [
          'bots', '--swarming', 'https://localhost:1',
          '--dimension', 'os', 'Windows',
        ])
    expected = (
        u'swarm2\n  {"cores": "8", "cpu": ["x86", "x86-64"], "cygwin": "0", '
          '"gpu": ["15ad", "15ad:0405", "VMware Virtual SVGA 3D Graphics '
          'Adapter"], "hostname": "swarm2.example.com", "id": "swarm2", '
          '"integrity": "high", "os": ["Windows", "Windows-6.1"]}\n')
    self._check_output(expected, '')

  def test_bots_filter_keep_dead(self):
    main(
        [
          'bots', '--swarming', 'https://localhost:1',
          '--dimension', 'os', 'Linux', '--keep-dead',
        ])
    expected = (
        u'swarm1\n  {"cores": "8", "cpu": ["x86", "x86-64"], "gpu": [], '
          '"hostname": "swarm1.example.com", "id": "swarm1", "os": ["Linux", '
          '"Linux-12.04"]}\n'
        u'swarm4\n'
        u'  {"cores": "8", "cpu": ["x86", "x86-64"], "gpu": [], "hostname": '
          '"swarm4.example.com", "id": "swarm4", "os": ["Linux", '
          '"Linux-12.04"]}\n'
        u'  task: 14856971a64c601\n')
    self._check_output(expected, '')

  def test_bots_filter_dead_only(self):
    main(
        [
          'bots', '--swarming', 'https://localhost:1',
          '--dimension', 'os', 'Linux', '--dead-only',
        ])
    expected = (
        u'swarm1\n  {"cores": "8", "cpu": ["x86", "x86-64"], "gpu": [], '
          '"hostname": "swarm1.example.com", "id": "swarm1", "os": ["Linux", '
          '"Linux-12.04"]}\n')
    self._check_output(expected, '')


def gen_run_isolated_out_hack_log(isolate_server, namespace, isolated_hash):
  data = {
    'hash': isolated_hash,
    'namespace': namespace,
    'storage': isolate_server,
  }
  return (SWARM_OUTPUT_SUCCESS +
      '[run_isolated_out_hack]%s[/run_isolated_out_hack]\n' % (
          json.dumps(data, sort_keys=True, separators=(',',':'))))


class ExtractOutputFilesLocationTest(auto_stub.TestCase):
  def test_ok(self):
    task_log = '\n'.join((
      'some log',
      'some more log',
      gen_run_isolated_out_hack_log('https://fake', 'default', '12345'),
      'more log',
    ))
    self.assertEqual(
        {'hash': '12345',
         'namespace': 'default',
         'server': 'https://fake',
         'view_url': 'https://fake/browse?namespace=default&hash=12345'},
        swarming.extract_output_files_location(task_log))

  def test_empty(self):
    task_log = '\n'.join((
      'some log',
      'some more log',
      '[run_isolated_out_hack]',
      '[/run_isolated_out_hack]',
    ))
    self.assertEqual(
        None,
        swarming.extract_output_files_location(task_log))

  def test_missing(self):
    task_log = '\n'.join((
      'some log',
      'some more log',
      'more log',
    ))
    self.assertEqual(
        None,
        swarming.extract_output_files_location(task_log))

  def test_corrupt(self):
    task_log = '\n'.join((
      'some log',
      'some more log',
      '[run_isolated_out_hack]',
      '{"hash": "12345","namespace":}',
      '[/run_isolated_out_hack]',
      'more log',
    ))
    self.assertEqual(
        None,
        swarming.extract_output_files_location(task_log))

  def test_not_url(self):
    task_log = '\n'.join((
      'some log',
      'some more log',
      gen_run_isolated_out_hack_log('/local/path', 'default', '12345'),
      'more log',
    ))
    self.assertEqual(
        None,
        swarming.extract_output_files_location(task_log))


class TaskOutputCollectorTest(auto_stub.TestCase):
  def setUp(self):
    super(TaskOutputCollectorTest, self).setUp()

    # Silence error log.
    self.mock(logging, 'error', lambda *_, **__: None)

    # Collect calls to 'isolateserver.fetch_isolated'.
    self.fetch_isolated_calls = []
    def fetch_isolated(isolated_hash, storage, cache, outdir, require_command):
      self.fetch_isolated_calls.append(
          (isolated_hash, storage, cache, outdir, require_command))
    # Ensure mock has exact same signature as the original, otherwise tests may
    # miss changes to real 'fetch_isolated' arg list.
    self.assertEqual(
        inspect.getargspec(swarming.isolateserver.fetch_isolated),
        inspect.getargspec(fetch_isolated))
    self.mock(swarming.isolateserver, 'fetch_isolated', fetch_isolated)

    # TaskOutputCollector creates directories. Put them in a temp directory.
    self.tempdir = tempfile.mkdtemp(prefix='swarming_test')

  def tearDown(self):
    shutil.rmtree(self.tempdir)
    super(TaskOutputCollectorTest, self).tearDown()

  def test_works(self):
    # Output logs of shards.
    logs = [
      gen_run_isolated_out_hack_log('https://server', 'namespace', 'hash1'),
      gen_run_isolated_out_hack_log('https://server', 'namespace', 'hash2'),
      SWARM_OUTPUT_SUCCESS,
    ]

    # Feed three shard results to collector, last one without output files.
    collector = swarming.TaskOutputCollector(
        self.tempdir, 'task/name', len(logs))
    for index, log in enumerate(logs):
      collector.process_shard_result(index, gen_data(log, '0, 0'))
    summary = collector.finalize()

    # Ensure it fetches the files from first two shards only.
    expected_calls = [
      ('hash1', None, None, os.path.join(self.tempdir, '0'), False),
      ('hash2', None, None, os.path.join(self.tempdir, '1'), False),
    ]
    self.assertEqual(len(expected_calls), len(self.fetch_isolated_calls))
    storage_instances = set()
    for expected, used in zip(expected_calls, self.fetch_isolated_calls):
      isolated_hash, storage, cache, outdir, require_command = used
      storage_instances.add(storage)
      # Compare everything but |storage| and |cache| (use None in their place).
      self.assertEqual(
          expected, (isolated_hash, None, None, outdir, require_command))
      # Ensure cache is set.
      self.assertTrue(cache)

    # Only one instance of Storage should be used.
    self.assertEqual(1, len(storage_instances))

    # Ensure storage is pointing to required location.
    storage = storage_instances.pop()
    self.assertEqual('https://server', storage.location)
    self.assertEqual('namespace', storage.namespace)

    # Ensure collected summary is correct.
    expected_summary = {
      'task_name': 'task/name',
      'shards': [
        gen_data(log, '0, 0') for index, log in enumerate(logs)
      ]
    }
    self.assertEqual(expected_summary, summary)

    # Ensure summary dumped to a file is correct as well.
    with open(os.path.join(self.tempdir, 'summary.json'), 'r') as f:
      summary_dump = json.load(f)
    self.assertEqual(expected_summary, summary_dump)

  def test_ensures_same_server(self):
    # Two shard results, attempt to use different servers.
    data = [
      gen_data(
        gen_run_isolated_out_hack_log('https://server1', 'namespace', 'hash1'),
        '0, 0'),
      gen_data(
        gen_run_isolated_out_hack_log('https://server2', 'namespace', 'hash2'),
        '0, 0'),
    ]

    # Feed them to collector.
    collector = swarming.TaskOutputCollector(self.tempdir, 'task/name', 2)
    for index, result in enumerate(data):
      collector.process_shard_result(index, result)
    collector.finalize()

    # Only first fetch is made, second one is ignored.
    self.assertEqual(1, len(self.fetch_isolated_calls))
    isolated_hash, storage, _, outdir, _ = self.fetch_isolated_calls[0]
    self.assertEqual(
        ('hash1', os.path.join(self.tempdir, '0')),
        (isolated_hash, outdir))
    self.assertEqual('https://server1', storage.location)


def clear_env_vars():
  for e in ('ISOLATE_SERVER', 'SWARMING_SERVER'):
    os.environ.pop(e, None)


if __name__ == '__main__':
  logging.basicConfig(
      level=logging.DEBUG if '-v' in sys.argv else logging.ERROR)
  if '-v' in sys.argv:
    unittest.TestCase.maxDiff = None
  clear_env_vars()
  unittest.main()
