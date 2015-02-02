#!/usr/bin/python
# Copyright (c) 2012 The Native Client Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""NEXE building script

This module will take a set of source files, include paths, library paths, and
additional arguments, and use them to build.
"""

import hashlib
import json
from optparse import OptionParser
import os
import re
import Queue
import shutil
import StringIO
import subprocess
import sys
import tempfile
import threading
import time
import urllib2

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import pynacl.platform

class Error(Exception):
  pass


def FixPath(path):
  # On Windows, |path| can be a long relative path: ..\..\..\..\out\Foo\bar...
  # If the full path -- os.path.join(os.getcwd(), path) -- is longer than 255
  # characters, then any operations that open or check for existence will fail.
  # We can't use os.path.abspath here, because that calls into a Windows
  # function that still has the path length limit. Instead, we'll cheat and
  # normalize the path lexically.
  path = os.path.normpath(os.path.join(os.getcwd(), path))
  if pynacl.platform.IsWindows():
    if len(path) > 255:
      raise Error('Path "%s" is too long (%d characters), and will fail.' % (
          path, len(path)))
  return path


def IsFile(path):
  return os.path.isfile(FixPath(path))


def MakeDir(outdir):
  outdir = FixPath(outdir)
  if outdir and not os.path.exists(outdir):
    # There may be a race creating this directory, so ignore failure.
    try:
      os.makedirs(outdir)
    except OSError:
      pass


def RemoveFile(path):
  os.remove(FixPath(path))


def OpenFile(path, mode='r'):
  return open(FixPath(path), mode)


def RemoveQuotes(opt):
  if opt and opt[0] == '"':
    assert opt[-1] == '"', opt
    return opt[1:-1].replace('\\"', '"')
  return opt


def ArgToList(opt):
  outlist = []
  if opt is None:
    return outlist
  optlist = opt.split(' ')
  for optitem in optlist:
    optitem = RemoveQuotes(optitem)
    if optitem:
      outlist.append(optitem)
  return outlist


def GetMTime(filepath):
  """GetMTime returns the last modification time of the file or None."""
  try:
    return os.path.getmtime(FixPath(filepath))
  except OSError:
    return None


def IsStale(out_ts, src_ts, rebuilt=False):
  # If either source or output timestamp was not available, assume stale.
  if not out_ts or not src_ts:
    return True

  # If just rebuilt timestamps may be equal due to time granularity.
  if rebuilt:
    return out_ts < src_ts
  # If about to build, be conservative and rebuilt just in case.
  return out_ts <= src_ts


def IsEnvFlagTrue(flag_name, default=False):
  """Return true when the given flag is true.

  Note:
  Any values that do not match the true pattern are False.

  Args:
    flag_name: a string name of a flag.
    default: default return value if the flag is not set.

  Returns:
    True if the flag is in the true pattern.  Otherwise False.
  """
  flag_value = os.environ.get(flag_name)
  if flag_value is None:
    return default
  return bool(re.search(r'^([tTyY]|1:?)', flag_value))


def GetIntegerEnv(flag_name, default=0):
  """Parses and returns integer environment variable.

  Args:
    flag_name: a string name of a flag.
    default: default return value if the flag is not set.

  Returns:
    Integer value of the flag.
  """
  flag_value = os.environ.get(flag_name)
  if flag_value is None:
    return default
  try:
    return int(flag_value)
  except ValueError:
    raise Error('Invalid ' + flag_name + ': ' + flag_value)


class Builder(object):
  """Builder object maintains options and generates build command-lines.

  The Builder object takes a set of script command-line options, and generates
  a set of paths, and command-line options for the NaCl toolchain.
  """
  def __init__(self, options):
    arch = options.arch
    self.arch = arch
    build_type = options.build.split('_')
    toolname = build_type[0]
    self.outtype = build_type[1]
    self.osname = pynacl.platform.GetOS()
    self.deferred_log = []

    # pnacl toolchain can be selected in three different ways
    # 1. by specifying --arch=pnacl directly to generate
    #    pexe targets.
    # 2. by specifying --build=newlib_translate to generated
    #    nexe via translation
    # 3. by specifying --build=newlib_{nexe,nlib}_pnacl use pnacl
    #    toolchain in native mode (e.g. the IRT shim)
    self.is_pnacl_toolchain = False
    if self.outtype == 'translate':
      self.is_pnacl_toolchain = True

    if len(build_type) > 2 and build_type[2] == 'pnacl':
      self.is_pnacl_toolchain = True

    if arch.endswith('-nonsfi'):
      arch = arch[:-len('-nonsfi')]

    if arch in ['x86-32', 'x86-64']:
      mainarch = 'x86'
      self.tool_prefix = 'x86_64-nacl-'
    elif arch == 'arm':
      self.tool_prefix = 'arm-nacl-'
      mainarch = 'arm'
    elif arch == 'mips':
      self.is_pnacl_toolchain = True
    elif arch == 'pnacl':
      self.is_pnacl_toolchain = True
    else:
      raise Error('Toolchain architecture %s not supported.' % arch)

    if toolname not in ['newlib', 'glibc']:
      raise Error('Toolchain of type %s not supported.' % toolname)

    if arch == 'arm' and toolname == 'glibc':
      raise Error('arm glibc not yet supported.')

    if arch == 'mips' and toolname == 'glibc':
      raise Error('mips glibc not supported.')

    if arch == 'pnacl' and toolname == 'glibc':
      raise Error('pnacl glibc not yet supported.')

    if self.is_pnacl_toolchain:
      self.tool_prefix = 'pnacl-'
      tool_subdir = 'pnacl_newlib'
    else:
      tool_subdir = 'nacl_%s_%s' % (mainarch, toolname)

    build_arch = pynacl.platform.GetArch()
    tooldir = os.path.join('%s_%s' % (self.osname, build_arch), tool_subdir)

    self.root_path = options.root
    self.nacl_path = os.path.join(self.root_path, 'native_client')

    project_path, project_name = os.path.split(options.name)
    self.outdir = options.objdir

    # Set the toolchain directories
    self.toolchain = os.path.join(options.toolpath, tooldir)
    self.toolbin = os.path.join(self.toolchain, 'bin')
    self.toolstamp = os.path.join(self.toolchain, 'stamp.prep')
    if not IsFile(self.toolstamp):
      raise Error('Could not find toolchain prep stamp file: ' + self.toolstamp)

    self.inc_paths = ArgToList(options.incdirs)
    self.lib_paths = ArgToList(options.libdirs)
    self.define_list = ArgToList(options.defines)

    self.name = options.name
    self.cmd_file = options.cmd_file
    self.BuildCompileOptions(options.compile_flags, self.define_list)
    self.BuildLinkOptions(options.link_flags)
    self.BuildArchiveOptions()
    self.verbose = options.verbose
    self.strip = options.strip
    self.empty = options.empty
    self.strip_all = options.strip_all
    self.strip_debug = options.strip_debug
    self.tls_edit = options.tls_edit
    self.finalize_pexe = options.finalize_pexe and arch == 'pnacl'
    goma_config = self.GetGomaConfig(options.gomadir, arch, toolname)
    self.gomacc = goma_config.get('gomacc', '')
    self.goma_burst = goma_config.get('burst', False)
    self.goma_threads = goma_config.get('threads', 1)

    # Define NDEBUG for Release builds.
    if options.build_config.startswith('Release'):
      self.compile_options.append('-DNDEBUG')

    # Use unoptimized native objects for debug IRT builds for faster compiles.
    if (self.is_pnacl_toolchain
        and (self.outtype == 'nlib'
             or self.outtype == 'nexe')
        and self.arch != 'pnacl'):
      if (options.build_config is not None
          and options.build_config.startswith('Debug')):
        self.compile_options.extend(['--pnacl-allow-translate',
                                     '--pnacl-allow-native',
                                     '-arch', self.arch])
        # Also use fast translation because we are still translating libc/libc++
        self.link_options.append('-Wt,-O0')

    self.irt_layout = options.irt_layout
    if self.irt_layout:
      # IRT constraints for auto layout.
      # IRT text can only go up to 256MB. Addresses after that are for data.
      # Reserve an extra page because:
      # * sel_ldr requires a HLT sled at the end of the dynamic code area;
      # * dynamic_load_test currently tests loading at the end of the dynamic
      #   code area.
      self.irt_text_max = 0x10000000 - 0x10000
      # Data can only go up to the sandbox_top - sizeof(stack).
      # NaCl allocates 16MB for the initial thread's stack (see
      # NACL_DEFAULT_STACK_MAX in sel_ldr.h).
      # Assume sandbox_top is 1GB, since even on x86-64 the limit would
      # only be 2GB (rip-relative references can only be +/- 2GB).
      sandbox_top = 0x40000000
      self.irt_data_max = sandbox_top - (16 << 20)
    self.Log('Compile options: %s' % self.compile_options)
    self.Log('Linker options: %s' % self.link_options)

  def GenNaClPath(self, path):
    """Helper which prepends path with the native client source directory."""
    return os.path.join(self.root_path, 'native_client', path)

  def GetBinName(self, name):
    """Helper which prepends executable with the toolchain bin directory."""
    return os.path.join(self.toolbin, self.tool_prefix + name)

  def GetCCompiler(self):
    """Helper which returns C compiler path."""
    if self.is_pnacl_toolchain:
      return self.GetBinName('clang')
    else:
      return self.GetBinName('gcc')

  def GetCXXCompiler(self):
    """Helper which returns C++ compiler path."""
    if self.is_pnacl_toolchain:
      return self.GetBinName('clang++')
    else:
      return self.GetBinName('g++')

  def GetAr(self):
    """Helper which returns ar path."""
    return self.GetBinName('ar')

  def GetStrip(self):
    """Helper which returns strip path."""
    return self.GetBinName('strip')

  def GetObjCopy(self):
    """Helper which returns objcopy path."""
    return self.GetBinName('objcopy')

  def GetReadElf(self):
    """Helper which returns readelf path."""
    return self.GetBinName('readelf')

  def GetPnaclFinalize(self):
    """Helper which returns pnacl-finalize path."""
    assert self.is_pnacl_toolchain
    return self.GetBinName('finalize')

  def BuildAssembleOptions(self, options):
    options = ArgToList(options)
    self.assemble_options = options + ['-I' + name for name in self.inc_paths]

  def DebugName(self):
    return self.name + '.debug'

  def UntaggedName(self):
    return self.name + '.untagged'

  def LinkOutputName(self):
    if (self.is_pnacl_toolchain and self.finalize_pexe or
        self.strip_all or self.strip_debug):
      return self.DebugName()
    else:
      return self.name

  def ArchiveOutputName(self):
    if self.strip_debug:
      return self.DebugName()
    else:
      return self.name

  def StripOutputName(self):
    return self.name

  def TranslateOutputName(self):
    return self.name

  def Soname(self):
    return self.name

  def BuildCompileOptions(self, options, define_list):
    """Generates compile options, called once by __init__."""
    options = ArgToList(options)
    # We want to shared gyp 'defines' with other targets, but not
    # ones that are host system dependent. Filtering them out.
    # This really should be better.
    # See: http://code.google.com/p/nativeclient/issues/detail?id=2936
    define_list = [define for define in define_list
                   if not (define.startswith('NACL_TARGET_ARCH=') or
                           define.startswith('NACL_TARGET_SUBARCH=') or
                           define.startswith('NACL_WINDOWS=') or
                           define.startswith('NACL_OSX=') or
                           define.startswith('NACL_LINUX=') or
                           define.startswith('NACL_ANDROID=') or
                           define == 'COMPONENT_BUILD' or
                           'WIN32' in define or
                           'WINDOWS' in define or
                           'WINVER' in define)]
    define_list.extend(['NACL_WINDOWS=0',
                        'NACL_OSX=0',
                        'NACL_LINUX=0',
                        'NACL_ANDROID=0'])
    options += ['-D' + define for define in define_list]
    self.compile_options = options + ['-I' + name for name in self.inc_paths]

  def BuildLinkOptions(self, options):
    """Generates link options, called once by __init__."""
    options = ArgToList(options)
    if self.outtype == 'nso':
      options += ['-Wl,-rpath-link,' + name for name in self.lib_paths]
      options += ['-shared']
      options += ['-Wl,-soname,' + os.path.basename(self.Soname())]
    self.link_options = options + ['-L' + name for name in self.lib_paths]

  def BuildArchiveOptions(self):
    """Generates link options, called once by __init__."""
    self.archive_options = []

  def Log(self, msg):
    if self.verbose:
      sys.stderr.write(str(msg) + '\n')
    else:
      self.deferred_log.append(str(msg) + '\n')

  def EmitDeferredLog(self):
    for line in self.deferred_log:
      sys.stderr.write(line)
    self.deferred_log = []

  def Run(self, cmd_line, get_output=False, possibly_batch=True, **kwargs):
    """Helper which runs a command line.

    Returns the error code if get_output is False.
    Returns the output if get_output is True.
    """

    # For POSIX style path on windows for POSIX based toolchain
    # (just for arguments, not for the path to the command itself)
    cmd_line = [cmd_line[0]] + [cmd.replace('\\', '/') for cmd in cmd_line[1:]]
    # Windows has a command line length limitation of 8191 characters.
    temp_file = None
    if len(' '.join(cmd_line)) > 8000:
      with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(' '.join(cmd_line[1:]))
      cmd_line = [cmd_line[0], '@' + temp_file.name]

    self.Log(' '.join(cmd_line))
    try:
      runner = subprocess.call
      if get_output:
        runner = subprocess.check_output
      if (possibly_batch and self.is_pnacl_toolchain and
          pynacl.platform.IsWindows()):
        # PNaCl toolchain executable is a script, not a binary, so it doesn't
        # want to run on Windows without a shell
        result = runner(' '.join(cmd_line), shell=True, **kwargs)
      else:
        result = runner(cmd_line, **kwargs)
    except Exception as err:
      raise Error('%s\nFAILED: %s' % (' '.join(cmd_line), str(err)))
    finally:
      if temp_file is not None:
        RemoveFile(temp_file.name)
    return result

  def GetObjectName(self, src):
    if self.strip:
      src = src.replace(self.strip,'')
    # Hash the full path of the source file and add 32 bits of that hash onto
    # the end of the object file name.  This helps disambiguate files with the
    # same name, because all of the object files are placed into the same
    # directory.  Technically, the correct solution would be to preserve the
    # directory structure of the input source files inside the object file
    # directory, but doing that runs the risk of running into filename length
    # issues on Windows.
    h = hashlib.sha1()
    h.update(src)
    wart = h.hexdigest()[:8]
    _, filename = os.path.split(src)
    filename, _ = os.path.splitext(filename)
    return os.path.join(self.outdir, filename + '_' + wart + '.o')

  def CleanOutput(self, out):
    if IsFile(out):
      # Since nobody can remove a file opened by somebody else on Windows,
      # we will retry removal.  After trying certain times, we gives up
      # and reraise the WindowsError.
      retry = 0
      while True:
        try:
          RemoveFile(out)
          return
        except WindowsError, inst:
          if retry > 5:
            raise
          self.Log('WindowsError %s while removing %s retry=%d' %
                   (inst, out, retry))
        sleep_time = 2**retry
        sleep_time = sleep_time if sleep_time < 10 else 10
        time.sleep(sleep_time)
        retry += 1

  def FixWindowsPath(self, path):
    # The windows version of the nacl toolchain returns badly
    # formed system header paths. As we do want changes in the
    # toolchain to trigger rebuilds, compensate by detecting
    # malformed paths (starting with /libexec/) and assume these
    # are actually toolchain relative.
    #
    # Additionally, in some cases the toolchains emit cygwin paths
    # which don't work in a win32 python.
    # Assume they are all /cygdrive/ relative and convert to a
    # drive letter.
    cygdrive = '/cygdrive/'
    if path.startswith('/cygdrive/'):
      path = os.path.normpath(
          path[len(cygdrive)] + ':' + path[len(cygdrive)+1:])
    elif path.startswith('/libexec/'):
      path = os.path.normpath(os.path.join(self.toolchain, path[1:]))
    return path

  def GetGomaConfig(self, gomadir, arch, toolname):
    """Returns a goma config dictionary if goma is available or {}."""

    # Start goma support from os/arch/toolname that have been tested.
    # Set NO_NACL_GOMA=true to force to avoid using goma.
    default_no_nacl_goma = True if pynacl.platform.IsWindows() else False
    if (arch not in ['x86-32', 'x86-64', 'pnacl']
        or toolname not in ['newlib', 'glibc']
        or IsEnvFlagTrue('NO_NACL_GOMA', default=default_no_nacl_goma)
        or IsEnvFlagTrue('GOMA_DISABLED')):
      return {}

    goma_config = {}
    gomacc_base = 'gomacc.exe' if pynacl.platform.IsWindows() else 'gomacc'
    # Search order of gomacc:
    # --gomadir command argument -> GOMA_DIR env. -> PATH env.
    search_path = []
    # 1. --gomadir in the command argument.
    if gomadir:
      search_path.append(gomadir)
    # 2. Use GOMA_DIR environment variable if exist.
    goma_dir_env = os.environ.get('GOMA_DIR')
    if goma_dir_env:
      search_path.append(goma_dir_env)
    # 3. Append PATH env.
    path_env = os.environ.get('PATH')
    if path_env:
      search_path.extend(path_env.split(os.path.pathsep))

    for directory in search_path:
      gomacc = os.path.join(directory, gomacc_base)
      if os.path.isfile(gomacc):
        try:
          port = int(subprocess.Popen(
              [gomacc, 'port'],
              stdout=subprocess.PIPE).communicate()[0].strip())
          status = urllib2.urlopen(
              'http://127.0.0.1:%d/healthz' % port).read().strip()
          if status == 'ok':
            goma_config['gomacc'] = gomacc
            break
        except (OSError, ValueError, urllib2.URLError) as e:
          # Try another gomacc in the search path.
          self.Log('Strange gomacc %s found, try another one: %s' % (gomacc, e))

    if goma_config:
      goma_config['burst'] = IsEnvFlagTrue('NACL_GOMA_BURST')
      default_threads = 100 if pynacl.platform.IsLinux() else 10
      goma_config['threads'] = GetIntegerEnv('NACL_GOMA_THREADS',
                                             default=default_threads)
    return goma_config

  def NeedsRebuild(self, outd, out, src, rebuilt=False):
    if not IsFile(self.toolstamp):
      if rebuilt:
        raise Error('Could not find toolchain stamp file %s.' % self.toolstamp)
      return True
    if not IsFile(self.cmd_file):
      if rebuilt:
        raise Error('Could not find cmd file %s.' % self.cmd_file)
      return True
    if not IsFile(outd):
      if rebuilt:
        raise Error('Could not find dependency file %s.' % outd)
      return True
    if not IsFile(out):
      if rebuilt:
        raise Error('Could not find output file %s.' % out)
      return True

    inputs = [__file__, self.toolstamp, src, self.cmd_file]
    outputs = [out, outd]

    # Find their timestamps if any.
    input_times = [(GetMTime(f), f) for f in inputs]
    output_times = [(GetMTime(f), f) for f in outputs]

    # All inputs must exist.
    missing_inputs = [p[1] for p in input_times if p[0] is None]
    if missing_inputs:
      raise Error('Missing inputs: %s' % str(missing_inputs))

    # Rebuild if any outputs are missing.
    missing_outputs = [p[1] for p in output_times if p[0] is None]
    if missing_outputs:
      if rebuilt:
        raise Error('Outputs missing after rebuild: %s' % str(missing_outputs))
      return True

    newest_input = max(input_times)
    oldest_output = min(output_times)

    if IsStale(oldest_output[0], newest_input[0], rebuilt):
      if rebuilt:
        raise Error('Output %s is older than toolchain stamp %s' % (
            oldest_output[1], newest_input[1]))
      return True

    # Decode emitted makefile.
    with open(FixPath(outd), 'r') as fh:
      deps = fh.read()
    # Remove line continuations
    deps = deps.replace('\\\n', ' ')
    deps = deps.replace('\n', '')
    # The dependencies are whitespace delimited following the first ':'
    # (that is not part of a windows drive letter)
    deps = deps.split(':', 1)
    if pynacl.platform.IsWindows() and len(deps[0]) == 1:
      # The path has a drive letter, find the next ':'
      deps = deps[1].split(':', 1)[1]
    else:
      deps = deps[1]
    deps = deps.split()
    if pynacl.platform.IsWindows():
      deps = [self.FixWindowsPath(d) for d in deps]
    # Check if any input has changed.
    for filename in deps:
      file_tm = GetMTime(filename)
      if IsStale(oldest_output[0], file_tm, rebuilt):
        if rebuilt:
          raise Error('Dependency %s is older than output %s.' % (
              filename, oldest_output[1]))
        return True
    return False

  def Compile(self, src):
    """Compile the source with pre-determined options."""

    compile_options = self.compile_options[:]
    _, ext = os.path.splitext(src)
    if ext in ['.c', '.S']:
      bin_name = self.GetCCompiler()
      compile_options.append('-std=gnu99')
      if self.is_pnacl_toolchain and ext == '.S':
        compile_options.append('-arch')
        compile_options.append(self.arch)
    elif ext in ['.cc', '.cpp']:
      compile_options.append('-std=gnu++0x')
      compile_options.append('-Wno-deprecated-register')
      bin_name = self.GetCXXCompiler()
    else:
      if ext != '.h':
        self.Log('Skipping unknown type %s for %s.' % (ext, src))
      return None

    # This option is only applicable to C, and C++ compilers warn if
    # it is present, so remove it for C++ to avoid the warning.
    if ext != '.c' and '-Wstrict-prototypes' in compile_options:
      compile_options.remove('-Wstrict-prototypes')

    self.Log('\nCompile %s' % src)

    out = self.GetObjectName(src)
    outd = out + '.d'

    # Don't rebuild unneeded.
    if not self.NeedsRebuild(outd, out, src):
      return out

    MakeDir(os.path.dirname(out))
    self.CleanOutput(out)
    self.CleanOutput(outd)
    cmd_line = [bin_name, '-c', src, '-o', out,
                '-MD', '-MF', outd] + compile_options
    if self.gomacc:
      cmd_line.insert(0, self.gomacc)
    err = self.Run(cmd_line, out)
    if err:
      self.CleanOutput(outd)
      raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))
    else:
      try:
        self.NeedsRebuild(outd, out, src, True)
      except Error as e:
        raise Error('Failed to compile %s to %s with deps %s and cmdline:\t%s'
                    '\nNeedsRebuild returned error: %s' % (
                        src, out, outd, ' '.join(cmd_line), e))
    return out

  def GetIRTLayout(self, irt_file):
    """Check if the IRT's data and text segment fit layout constraints and
       get sizes of the IRT's text and data segments.

    Returns a tuple containing:
      * whether the IRT data/text top addresses fit within the max limit
      * current data/text top addrs
      * size of text and data segments
    """
    cmd_line = [self.GetReadElf(), '-W', '--segments', irt_file]
    # Put LC_ALL=C in the environment for readelf, so that its messages
    # will reliably match what we're looking for rather than being in some
    # other language and/or character set.
    env = dict(os.environ)
    env['LC_ALL'] = 'C'
    seginfo = self.Run(cmd_line, get_output=True, env=env)
    lines = seginfo.splitlines()
    ph_start = -1
    for i, line in enumerate(lines):
      if line == 'Program Headers:':
        ph_start = i + 1
        break
    if ph_start == -1:
      raise Error('Could not find Program Headers start: %s\n' % lines)
    seg_lines = lines[ph_start:]
    text_bottom = 0
    text_top = 0
    data_bottom = 0
    data_top = 0
    for line in seg_lines:
      pieces = line.split()
      # Type, Offset, Vaddr, Paddr, FileSz, MemSz, Flg(multiple), Align
      if len(pieces) >= 8 and pieces[0] == 'LOAD':
        # Vaddr + MemSz
        segment_bottom = int(pieces[2], 16)
        segment_top = segment_bottom + int(pieces[5], 16)
        if pieces[6] == 'R' and pieces[7] == 'E':
          text_top = max(segment_top, text_top)
          if text_bottom == 0:
            text_bottom = segment_bottom
          else:
            text_bottom = min(segment_bottom, text_bottom)
          continue
        if pieces[6] == 'R' or pieces[6] == 'RW':
          data_top = max(segment_top, data_top)
          if data_bottom == 0:
            data_bottom = segment_bottom
          else:
            data_bottom = min(segment_bottom, data_bottom)
          continue
    if text_top == 0 or data_top == 0 or text_bottom == 0 or data_bottom == 0:
      raise Error('Could not parse IRT Layout: text_top=0x%x text_bottom=0x%x\n'
                  '                            data_top=0x%x data_bottom=0x%x\n'
                  'readelf output: %s\n' % (text_top, text_bottom,
                                            data_top, data_bottom, lines))
    return ((text_top <= self.irt_text_max and
            data_top <= self.irt_data_max), text_top, data_top,
            text_top - text_bottom, data_top - data_bottom)

  def AdjustIRTLinkToFit(self, cmd_line, text_size, data_size):
    """Adjust the linker options so that the IRT's data and text segment fit."""
    def RoundDownToAlign(x):
      return x - (x % 0x10000)
    def AdjustFlag(flag_name, size, expected_max):
      self.Log('IRT %s size is %s' % (flag_name, size))
      new_start = RoundDownToAlign(expected_max - size)
      self.Log('Setting link flag %s to %s' % (flag_name,
                                            hex(new_start)))
      cmd_line.extend(["-Wl,%s=%s" % (flag_name, hex(new_start))])
    AdjustFlag('-Ttext-segment', text_size, self.irt_text_max)
    AdjustFlag('-Trodata-segment', data_size, self.irt_data_max)
    self.Log('Adjusted link options to %s' % ' '.join(cmd_line))
    return cmd_line

  def RunLink(self, cmd_line, link_out):
    self.CleanOutput(link_out)
    err = self.Run(cmd_line, link_out)
    if err:
      raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))

  def Link(self, srcs):
    """Link these objects with predetermined options and output name."""
    out = self.LinkOutputName()
    self.Log('\nLink %s' % out)
    bin_name = self.GetCXXCompiler()

    link_out = out
    if self.tls_edit is not None:
      link_out = out + '.raw'

    MakeDir(os.path.dirname(link_out))

    cmd_line = [bin_name, '-o', link_out, '-Wl,--as-needed']
    if not self.empty:
      cmd_line += srcs
    cmd_line += self.link_options

    self.RunLink(cmd_line, link_out)

    if self.irt_layout:
      (fits, text_top, data_top,
       text_size, data_size) = self.GetIRTLayout(link_out)
      # fits is ignored after first link, since correct parameters were not
      # present in the command line (as they were unknown at the time).
      cmd_line = self.AdjustIRTLinkToFit(cmd_line, text_size, data_size)
      self.RunLink(cmd_line, link_out)
      (fits, text_top, data_top,
       text_size, data_size) = self.GetIRTLayout(link_out)
      if not fits:
        raise Error('Already re-linked IRT and it still does not fit:\n'
                    'text_top=0x%x and data_top=0x%x\n' % (
                        text_top, data_top))
      self.Log('IRT layout fits: text_top=0x%x and data_top=0x%x' %
               (text_top, data_top))

    if self.tls_edit is not None:
      tls_edit_cmd = [FixPath(self.tls_edit), link_out, out]
      tls_edit_err = self.Run(tls_edit_cmd, out, possibly_batch=False)
      if tls_edit_err:
        raise Error('FAILED with %d: %s' % (err, ' '.join(tls_edit_cmd)))

    return out

  # For now, only support translating a pexe, and not .o file(s)
  def Translate(self, src):
    """Translate a pexe to a nexe."""
    out = self.TranslateOutputName()
    self.Log('\nTranslate %s' % out)
    bin_name = self.GetBinName('translate')
    cmd_line = [bin_name, '-arch', self.arch, src, '-o', out]
    cmd_line += self.link_options

    err = self.Run(cmd_line, out)
    if err:
      raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))
    return out

  def Archive(self, srcs):
    """Archive these objects with predetermined options and output name."""
    out = self.ArchiveOutputName()
    self.Log('\nArchive %s' % out)

    if '-r' in self.link_options:
      bin_name = self.GetCXXCompiler()
      cmd_line = [bin_name, '-o', out, '-Wl,--as-needed']
      if not self.empty:
        cmd_line += srcs
      cmd_line += self.link_options
    else:
      bin_name = self.GetAr()
      cmd_line = [bin_name, '-rc', out]
      if not self.empty:
        cmd_line += srcs

    MakeDir(os.path.dirname(out))
    self.CleanOutput(out)
    err = self.Run(cmd_line, out)
    if err:
      raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))
    return out

  def Strip(self, src):
    """Strip the NEXE"""
    self.Log('\nStrip %s' % src)

    out = self.StripOutputName()
    pre_debug_tagging = self.UntaggedName()
    self.CleanOutput(out)
    self.CleanOutput(pre_debug_tagging)

    # Strip from foo.debug to foo.untagged.
    strip_name = self.GetStrip()
    strip_option = '--strip-all' if self.strip_all else '--strip-debug'
    # pnacl does not have an objcopy so there are no way to embed a link
    if self.is_pnacl_toolchain:
      cmd_line = [strip_name, strip_option, src, '-o', out]
      err = self.Run(cmd_line, out)
      if err:
        raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))
    else:
      cmd_line = [strip_name, strip_option, src, '-o', pre_debug_tagging]
      err = self.Run(cmd_line, pre_debug_tagging)
      if err:
        raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))

      # Tag with a debug link to foo.debug copying from foo.untagged to foo.
      objcopy_name = self.GetObjCopy()
      cmd_line = [objcopy_name, '--add-gnu-debuglink', src,
                  pre_debug_tagging, out]
      err = self.Run(cmd_line, out)
      if err:
        raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))

      # Drop the untagged intermediate.
      self.CleanOutput(pre_debug_tagging)

    return out

  def Finalize(self, src):
    """Finalize the PEXE"""
    self.Log('\nFinalize %s' % src)

    out = self.StripOutputName()
    self.CleanOutput(out)
    bin_name = self.GetPnaclFinalize()
    cmd_line = [bin_name, src, '-o', out]
    err = self.Run(cmd_line, out)
    if err:
      raise Error('FAILED with %d: %s' % (err, ' '.join(cmd_line)))
    return out

  def Generate(self, srcs):
    """Generate final output file.

    Link or Archive the final output file, from the compiled sources.
    """
    if self.outtype in ['nexe', 'pexe', 'nso']:
      out = self.Link(srcs)
      if self.is_pnacl_toolchain and self.finalize_pexe:
        # Note: pnacl-finalize also does stripping.
        self.Finalize(out)
      elif self.strip_all or self.strip_debug:
        self.Strip(out)
    elif self.outtype in ['nlib', 'plib']:
      out = self.Archive(srcs)
      if self.strip_debug:
        self.Strip(out)
      elif self.strip_all:
        raise Error('FAILED: --strip-all on libs will result in unusable libs.')
    else:
      raise Error('FAILED: Unknown outtype: %s' % (self.outtype))


def UpdateBuildArgs(args, filename):
  new_cmd = json.dumps(args)

  try:
    with open(filename, 'r') as fileobj:
      old_cmd = fileobj.read()
  except:
    old_cmd = None

  if old_cmd == new_cmd:
    return False

  with open(filename, 'w') as fileobj:
    fileobj.write(new_cmd)
  return True


def Main(argv):
  parser = OptionParser()
  parser.add_option('--empty', dest='empty', default=False,
                    help='Do not pass sources to library.', action='store_true')
  parser.add_option('--no-suffix', dest='suffix', default=True,
                    help='Do not append arch suffix.', action='store_false')
  parser.add_option('--strip-debug', dest='strip_debug', default=False,
                    help='Strip the NEXE for debugging', action='store_true')
  parser.add_option('--strip-all', dest='strip_all', default=False,
                    help='Strip the NEXE for production', action='store_true')
  parser.add_option('--strip', dest='strip', default='',
                    help='Strip the filename')
  parser.add_option('--nonstable-pnacl', dest='finalize_pexe', default=True,
                    help='Do not finalize pnacl bitcode for ABI stability',
                    action='store_false')
  parser.add_option('--source-list', dest='source_list',
                    help='Filename to load a source list from')
  parser.add_option('--tls-edit', dest='tls_edit', default=None,
                    help='tls_edit location if TLS should be modified for IRT')
  parser.add_option('--irt-layout', dest='irt_layout', default=False,
                    help='Apply the IRT layout (pick data/text seg addresses)',
                    action='store_true')
  parser.add_option('-a', '--arch', dest='arch',
                    help='Set target architecture')
  parser.add_option('-c', '--compile', dest='compile_only', default=False,
                    help='Compile only.', action='store_true')
  parser.add_option('-i', '--include-dirs', dest='incdirs',
                    help='Set include directories.')
  parser.add_option('-l', '--lib-dirs', dest='libdirs',
                    help='Set library directories.')
  parser.add_option('-n', '--name', dest='name',
                    help='Base path and name of the nexe.')
  parser.add_option('-o', '--objdir', dest='objdir',
                    help='Base path of the object output dir.')
  parser.add_option('-r', '--root', dest='root',
                    help='Set the root directory of the sources')
  parser.add_option('--product-directory', dest='product_directory',
                    help='Set the root directory of the build')
  parser.add_option('-b', '--build', dest='build',
                    help='Set build type (<toolchain>_<outtype>, ' +
                    'where toolchain is newlib or glibc and outtype is ' +
                    'one of nexe, nlib, nso, pexe, or translate)')
  parser.add_option('--compile_flags', dest='compile_flags',
                    help='Set compile flags.')
  parser.add_option('--defines', dest='defines',
                    help='Set defines')
  parser.add_option('--link_flags', dest='link_flags',
                    help='Set link flags.')
  parser.add_option('-v', '--verbose', dest='verbose', default=False,
                    help='Enable verbosity', action='store_true')
  parser.add_option('-t', '--toolpath', dest='toolpath',
                    help='Set the path for of the toolchains.')
  parser.add_option('--config-name', dest='build_config',
                    help='GYP build configuration name (Release/Debug)')
  parser.add_option('--gomadir', dest='gomadir',
                    help='Path of the goma directory.')
  options, files = parser.parse_args(argv[1:])

  if options.name is None:
    parser.error('--name is required!')
  if options.build_config is None:
    parser.error('--config-name is required!')
  if options.root is None:
    parser.error('--root is required!')
  if options.arch is None:
    parser.error('--arch is required!')
  if options.build is None:
    parser.error('--build is required!')

  if not argv:
    parser.print_help()
    return 1

  # Compare command-line options to last run, and force a rebuild if they
  # have changed.
  options.cmd_file = options.name + '.cmd'
  UpdateBuildArgs(argv, options.cmd_file)

  try:
    if options.source_list:
      source_list_handle = open(options.source_list, 'r')
      source_list = source_list_handle.read().splitlines()
      source_list_handle.close()

      for file_name in source_list:
        file_name = RemoveQuotes(file_name)
        if "$" in file_name:
          # Only require product directory if we need to interpolate it.  This
          # provides backwards compatibility in the cases where we don't need to
          # interpolate.  The downside is this creates a subtle landmine.
          if options.product_directory is None:
            parser.error('--product-dir is required')
          product_dir = options.product_directory
          # Normalize to forward slashes because re.sub interprets backslashes
          # as escape characters. This also simplifies the subsequent regexes.
          product_dir = product_dir.replace('\\', '/')
          # Remove fake child that may be apended to the path.
          # See untrusted.gypi.
          product_dir = re.sub(r'/+xyz$', '', product_dir)
          # The "make" backend can have an "obj" interpolation variable.
          file_name = re.sub(r'\$!?[({]?obj[)}]?', product_dir + '/obj',
                             file_name)
          # Expected patterns:
          # $!PRODUCT_DIR in ninja.
          # $(builddir) in make.
          # $(OutDir) in MSVC.
          # $(BUILT_PRODUCTS_DIR) in xcode.
          # Also strip off and re-add the trailing directory seperator because
          # different platforms are inconsistent on if it's there or not.
          # HACK assume only the product directory is the only var left.
          file_name = re.sub(r'\$!?[({]?\w+[)}]?/?', product_dir + '/',
                             file_name)
          assert "$" not in file_name, file_name
        files.append(file_name)

    # Use set instead of list not to compile the same file twice.
    # To keep in mind that the order of files may differ from the .gypcmd file,
    # the set is not converted to a list.
    # Having duplicated files can cause race condition of compiling during
    # parallel build using goma.
    # TODO(sbc): remove the duplication and turn it into an error.
    files = set(files)

    # Fix slash style to insulate invoked toolchains.
    options.toolpath = os.path.normpath(options.toolpath)

    build = Builder(options)
    objs = []

    if build.outtype == 'translate':
      # Just translate a pexe to a nexe
      if len(files) != 1:
        parser.error('Pexe translation requires exactly one input file.')
      build.Translate(list(files)[0])
      return 0

    if build.gomacc and (build.goma_burst or build.goma_threads > 1):
      returns = Queue.Queue()

      # Push all files into the inputs queue
      inputs = Queue.Queue()
      for filename in files:
        inputs.put(filename)

      def CompileThread(input_queue, output_queue):
        try:
          while True:
            try:
              filename = input_queue.get_nowait()
            except Queue.Empty:
              return
            output_queue.put(build.Compile(filename))
        except Exception:
          # Put current exception info to the queue.
          output_queue.put(sys.exc_info())

      # Don't limit number of threads in the burst mode.
      if build.goma_burst:
        num_threads = len(files)
      else:
        num_threads = min(build.goma_threads, len(files))

      # Start parallel build.
      build_threads = []
      for _ in xrange(num_threads):
        thr = threading.Thread(target=CompileThread, args=(inputs, returns))
        thr.start()
        build_threads.append(thr)

      # Wait for results.
      for _ in files:
        out = returns.get()
        # An exception raised in the thread may come through the queue.
        # Raise it again here.
        if (isinstance(out, tuple) and len(out) == 3 and
            isinstance(out[1], Exception)):
          raise out[0], None, out[2]
        elif out:
          objs.append(out)

      assert inputs.empty()

      # Wait until all threads have stopped and verify that there are no more
      # results.
      for thr in build_threads:
        thr.join()
      assert returns.empty()

    else:  # slow path.
      for filename in files:
        out = build.Compile(filename)
        if out:
          objs.append(out)

    # Do not link if building an object. However we still want the output file
    # to be what was specified in options.name
    if options.compile_only:
      if len(objs) > 1:
        raise Error('--compile mode cannot be used with multiple sources')
      shutil.copy(objs[0], options.name)
    else:
      build.Generate(objs)
    return 0
  except Error as e:
    sys.stderr.write('%s\n' % e)
    return 1
  except:
    build.EmitDeferredLog()
    raise

if __name__ == '__main__':
  sys.exit(Main(sys.argv))