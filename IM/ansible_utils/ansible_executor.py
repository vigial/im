# IM - Infrastructure Manager
# Copyright (C) 2015 - GRyCAP - Universitat Politecnica de Valencia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more/etc/sudoers details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Some parts of this code are taken from the Ansible code
# (c) 2012-2014, Michael DeHaan <michael.dehaan@gmail.com>
#

import logging
import sys
import tempfile
import shutil
from datetime import datetime

from ansible import constants as C
from ansible.plugins.callback import CallbackBase
from ansible.utils.color import colorize, hostcolor
from ansible.utils.display import Display

from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.playbook import Playbook
from ansible.template import Templar
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.utils.ssh_functions import check_for_controlpersist


class IMDisplay(Display):

    def __init__(self, verbosity=0, output=None):
        self.output = output
        super(IMDisplay, self).__init__(verbosity)

    def display(self, msg, color=None, stderr=False,
                screen_only=False, log_only=False):
        if self.output:
            if isinstance(self.output, logging.Logger):
                self.output.info(msg)
            else:
                self.output.write("%s\n" % msg)
        else:
            sys.stdout.write(msg)
            sys.stdout.flush()


class AnsibleCallbacks(CallbackBase):

    '''
    This is the default callback interface, which simply prints messages
    to stdout when new callback events are received.
    '''

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'stdout'
    CALLBACK_NAME = 'ansible_callbacks_v2'

    def __init__(self, output=None):
        super(AnsibleCallbacks, self).__init__()
        self._display = IMDisplay(output=output)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if 'exception' in result._result:
            if self._display.verbosity < 3:
                # extract just the actual error message from the exception text
                error = result._result['exception'].strip().split('\n')[-1]
                msg = ("An exception occurred during task execution. To see "
                       "the full traceback, use -vvv. The error was: %s" % error)
            else:
                msg = ("An exception occurred during task execution. The full "
                       "traceback is:\n" + result._result['exception'])

            self._display.display(msg, color='red')

            # finally, remove the exception from the result so it's not shown
            # every time
            del result._result['exception']

        if result._task.loop and 'results' in result._result:
            self._process_items(result)
        else:
            if delegated_vars:
                self._display.display("fatal: [%s -> %s]: FAILED! => %s" % (result._host.get_name(
                ), delegated_vars['ansible_host'], self._dump_results(result._result)), color='red')
            else:
                self._display.display("fatal: [%s]: FAILED! => %s" % (
                    result._host.get_name(), self._dump_results(result._result)), color='red')

        if result._task.ignore_errors:
            self._display.display("...ignoring", color='cyan')

    def v2_runner_on_ok(self, result):

        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if result._task.action == 'include':
            return
        elif result._result.get('changed', False):
            if delegated_vars:
                msg = "changed: [%s -> %s]" % (result._host.get_name(),
                                               delegated_vars['ansible_host'])
            else:
                msg = "changed: [%s]" % result._host.get_name()
            color = 'yellow'
        else:
            if delegated_vars:
                msg = "ok: [%s -> %s]" % (result._host.get_name(),
                                          delegated_vars['ansible_host'])
            else:
                msg = "ok: [%s]" % result._host.get_name()
            color = 'green'

        if result._task.loop and 'results' in result._result:
            self._process_items(result)
        else:

            if ((self._display.verbosity > 0 or '_ansible_verbose_always' in result._result) and
                    '_ansible_verbose_override' not in result._result):
                msg += " => %s" % (self._dump_results(result._result),)
            self._display.display(msg, color=color)

        self._handle_warnings(result._result)

    def v2_runner_on_skipped(self, result):
        if C.DISPLAY_SKIPPED_HOSTS:
            if result._task.loop and 'results' in result._result:
                self._process_items(result)
            else:
                msg = "skipping: [%s]" % result._host.get_name()
                if ((self._display.verbosity > 0 or '_ansible_verbose_always' in result._result) and
                        '_ansible_verbose_override' not in result._result):
                    msg += " => %s" % self._dump_results(result._result)
                self._display.display(msg, color='cyan')

    def v2_runner_on_unreachable(self, result):
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if delegated_vars:
            self._display.display("fatal: [%s -> %s]: UNREACHABLE! => %s" % (result._host.get_name(
            ), delegated_vars['ansible_host'], self._dump_results(result._result)), color='red')
        else:
            self._display.display("fatal: [%s]: UNREACHABLE! => %s" % (
                result._host.get_name(), self._dump_results(result._result)), color='red')

    def v2_runner_item_on_ok(self, result):
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if result._task.action == 'include':
            return
        elif result._result.get('changed', False):
            msg = 'changed'
            color = 'yellow'
        else:
            msg = 'ok'
            color = 'green'

        if delegated_vars:
            msg += ": [%s -> %s]" % (result._host.get_name(), delegated_vars['ansible_host'])
        else:
            msg += ": [%s]" % result._host.get_name()

        msg += " => (item=%s)" % (self._get_item(result._result),)

        if ((self._display.verbosity > 0 or '_ansible_verbose_always' in result._result) and
                '_ansible_verbose_override' not in result._result):
            msg += " => %s" % self._dump_results(result._result)
        self._display.display(msg, color=color)

    def v2_runner_item_on_failed(self, result):
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if 'exception' in result._result:
            if self._display.verbosity < 3:
                # extract just the actual error message from the exception text
                error = result._result['exception'].strip().split('\n')[-1]
                msg = ("An exception occurred during task execution. To see the full traceback,"
                       " use -vvv. The error was: %s" % error)
            else:
                msg = ("An exception occurred during task execution."
                       " The full traceback is:\n" + result._result['exception'])

            self._display.display(msg, color="red")

        msg = "failed: "
        if delegated_vars:
            msg += "[%s -> %s]" % (result._host.get_name(), delegated_vars['ansible_host'])
        else:
            msg += "[%s]" % (result._host.get_name())

        self._display.display(msg + " (item=%s) => %s" % (self._get_item(result._result),
                                                          self._dump_results(result._result)),
                              color=C.COLOR_ERROR)
        self._handle_warnings(result._result)

    def v2_runner_item_on_skipped(self, result):
        if C.DISPLAY_SKIPPED_HOSTS:
            msg = "skipping: [%s] => (item=%s) " % (result._host.get_name(), self._get_item(result._result))
            if ((self._display.verbosity > 0 or '_ansible_verbose_always' in result._result) and
                    '_ansible_verbose_override' not in result._result):
                msg += " => %s" % self._dump_results(result._result)
            self._display.display(msg, color="cyan")

    def v2_playbook_on_no_hosts_matched(self):
        self._display.display("skipping: no hosts matched", color='cyan')

    def v2_playbook_on_no_hosts_remaining(self):
        self._display.banner("NO MORE HOSTS LEFT")

    def v2_playbook_on_task_start(self, task, is_conditional):
        self._display.banner("TASK [%s]" % task.get_name().strip())
        # Display current time
        self._display.display("%s" % datetime.now().strftime('%A %d %B %Y  %H:%M:%S.%f '))

        if self._display.verbosity > 2:
            path = task.get_path()
            if path:
                self._display.display("task path: %s" %
                                      path, color='dark gray')

    def v2_playbook_on_cleanup_task_start(self, task):
        self._display.banner("CLEANUP TASK [%s]" % task.get_name().strip())

    def v2_playbook_on_handler_task_start(self, task):
        self._display.banner("RUNNING HANDLER [%s]" % task.get_name().strip())

    def v2_playbook_on_play_start(self, play):
        name = play.get_name().strip()
        if not name:
            msg = "PLAY"
        else:
            msg = "PLAY [%s]" % name

        self._display.banner(msg)

    def v2_on_file_diff(self, result):
        if 'diff' in result._result and result._result['diff']:
            self._display.display(self._get_diff(result._result['diff']))

    def v2_playbook_item_on_ok(self, result):

        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if result._task.action == 'include':
            return
        elif result._result.get('changed', False):
            if delegated_vars:
                msg = "changed: [%s -> %s]" % (result._host.get_name(),
                                               delegated_vars['ansible_host'])
            else:
                msg = "changed: [%s]" % result._host.get_name()
            color = 'yellow'
        else:
            if delegated_vars:
                msg = "ok: [%s -> %s]" % (result._host.get_name(),
                                          delegated_vars['ansible_host'])
            else:
                msg = "ok: [%s]" % result._host.get_name()
            color = 'green'

        msg += " => (item=%s)" % (result._result['item'],)

        if ((self._display.verbosity > 0 or '_ansible_verbose_always' in result._result) and
                '_ansible_verbose_override' not in result._result):
            msg += " => %s" % self._dump_results(result._result)
        self._display.display(msg, color=color)

    def v2_playbook_item_on_failed(self, result):
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if 'exception' in result._result:
            if self._display.verbosity < 3:
                # extract just the actual error message from the exception text
                error = result._result['exception'].strip().split('\n')[-1]
                msg = ("An exception occurred during task execution. To see the full "
                       "traceback, use -vvv. The error was: %s" % error)
            else:
                msg = "An exception occurred during task execution. The full traceback is:\n" + \
                    result._result['exception']

            self._display.display(msg, color='red')

            # finally, remove the exception from the result so it's not shown
            # every time
            del result._result['exception']

        if delegated_vars:
            self._display.display("failed: [%s -> %s] => (item=%s) => %s" % (result._host.get_name(), delegated_vars[
                                  'ansible_host'], result._result['item'], self._dump_results(result._result)),
                                  color='red')
        else:
            self._display.display("failed: [%s] => (item=%s) => %s" % (result._host.get_name(
            ), result._result['item'], self._dump_results(result._result)), color='red')

        self._handle_warnings(result._result)

    def v2_playbook_item_on_skipped(self, result):
        msg = "skipping: [%s] => (item=%s) " % (
            result._host.get_name(), result._result['item'])
        if (self._display.verbosity >
                0 or '_ansible_verbose_always' in result._result) and '_ansible_verbose_override' not in result._result:
            msg += " => %s" % self._dump_results(result._result)
        self._display.display(msg, color='cyan')

    def v2_playbook_on_include(self, included_file):
        msg = 'included: %s for %s' % (included_file._filename, ", ".join(
            [h.name for h in included_file._hosts]))
        self._display.display(msg, color='cyan')

    def v2_playbook_on_stats(self, stats):
        self._display.banner("PLAY RECAP")

        hosts = sorted(stats.processed.keys())
        for h in hosts:
            t = stats.summarize(h)

            self._display.display(u"%s : %s %s %s %s" % (
                hostcolor(h, t),
                colorize(u'ok', t['ok'], 'green'),
                colorize(u'changed', t['changed'], 'yellow'),
                colorize(u'unreachable', t['unreachable'], 'red'),
                colorize(u'failed', t['failures'], 'red')),
                screen_only=True
            )

            self._display.display(u"%s : %s %s %s %s" % (
                hostcolor(h, t, False),
                colorize(u'ok', t['ok'], None),
                colorize(u'changed', t['changed'], None),
                colorize(u'unreachable', t['unreachable'], None),
                colorize(u'failed', t['failures'], None)),
                log_only=True
            )

        self._display.display("", screen_only=True)


class IMPlaybookExecutor(PlaybookExecutor):
    '''
    Simplified version of the PlaybookExecutor
    '''

    def __init__(self, playbook, inventory, variable_manager,
                 loader, options, passwords, output):
        self._playbook = playbook
        self._inventory = inventory
        self._variable_manager = variable_manager
        self._loader = loader
        self._options = options
        self.passwords = passwords
        self._unreachable_hosts = dict()

        self._tqm = TaskQueueManager(inventory=inventory,
                                     variable_manager=variable_manager,
                                     loader=loader, options=options,
                                     passwords=self.passwords)

        # Set out Callback as the stdout one to avoid stdout messages
        self._tqm._stdout_callback = AnsibleCallbacks(output)

        # Note: We run this here to cache whether the default ansible ssh
        # executable supports control persist.  Sometime in the future we may
        # need to enhance this to check that ansible_ssh_executable specified
        # in inventory is also cached.  We can't do this caching at the point
        # where it is used (in task_executor) because that is post-fork and
        # therefore would be discarded after every task.
        check_for_controlpersist(C.ANSIBLE_SSH_EXECUTABLE)

    def run(self):
        '''
        Run the given playbook, based on the settings in the play which
        may limit the runs to serialized groups, etc.
        '''
        # Create a specific dir for the local temp
        C.DEFAULT_LOCAL_TMP = tempfile.mkdtemp()

        result = 0
        try:
            pb = Playbook.load(self._playbook, variable_manager=self._variable_manager, loader=self._loader)

            # make sure the tqm has callbacks loaded
            self._tqm.load_callbacks()
            self._tqm.send_callback('v2_playbook_on_start', pb)

            for play in pb.get_plays():
                if play._included_path is not None:
                    self._loader.set_basedir(play._included_path)
                else:
                    self._loader.set_basedir(pb._basedir)

                # clear any filters which may have been applied to the
                # inventory
                self._inventory.remove_restriction()

                # Create a temporary copy of the play here, so we can run post_validate
                # on it without the templating changes affecting the
                # original object.
                all_vars = self._variable_manager.get_vars(play=play)
                templar = Templar(loader=self._loader, variables=all_vars)
                new_play = play.copy()
                new_play.post_validate(templar)

                self._tqm._unreachable_hosts.update(self._unreachable_hosts)

                previously_failed = len(self._tqm._failed_hosts)
                previously_unreachable = len(self._tqm._unreachable_hosts)

                # we are actually running plays
                batches = self._get_serialized_batches(new_play)
                if len(batches) == 0:
                    self._tqm.send_callback('v2_playbook_on_play_start', new_play)
                    self._tqm.send_callback('v2_playbook_on_no_hosts_matched')
                for batch in batches:
                    # restrict the inventory to the hosts in the serialized
                    # batch
                    self._inventory.restrict_to_hosts(batch)
                    # and run it...
                    result = self._tqm.run(play=play)

                    # break the play if the result equals the special return code
                    if result & self._tqm.RUN_FAILED_BREAK_PLAY != 0:
                        result = self._tqm.RUN_FAILED_HOSTS
                        break

                    # check the number of failures here, to see if they're above the maximum
                    # failure percentage allowed, or if any errors are fatal. If either of those
                    # conditions are met, we break out, otherwise we only break out if the entire
                    # batch failed
                    failed_hosts_count = len(self._tqm._failed_hosts) + len(self._tqm._unreachable_hosts) - \
                        (previously_failed + previously_unreachable)

                    if len(batch) == failed_hosts_count:
                        break

                    # update the previous counts so they don't accumulate incorrectly
                    # over multiple serial batches
                    previously_failed += len(self._tqm._failed_hosts) - previously_failed
                    previously_unreachable += len(self._tqm._unreachable_hosts) - previously_unreachable

                    # save the unreachable hosts from this batch
                    self._unreachable_hosts.update(self._tqm._unreachable_hosts)

                # if the last result wasn't zero or 3 (some hosts were unreachable),
                # break out of the serial batch loop
                if result not in (0, 3):
                    break

            self._tqm.send_callback('v2_playbook_on_stats', self._tqm._stats)

        finally:
            if self._tqm is not None:
                self._tqm.cleanup()

        try:
            # Remove the local temp
            shutil.rmtree(C.DEFAULT_LOCAL_TMP, True)
        except:
            pass

        return result