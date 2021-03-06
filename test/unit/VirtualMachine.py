#! /usr/bin/env python
#
# IM - Infrastructure Manager
# Copyright (C) 2011 - GRyCAP - Universitat Politecnica de Valencia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import unittest
import os

from IM.VirtualMachine import VirtualMachine
from radl import radl_parse
from mock import patch, MagicMock


class TestVirtualMachine(unittest.TestCase):
    """
    Class to test the VirtualMachineclass
    """

    def test_apps_to_install(self):
        radl_data = """
            system test (
            disk.0.applications contains (name = 'ansible.modules.grycap.clues') and
            disk.0.applications contains (name = 'java' and version='1.9')
            )"""
        radl = radl_parse.parse_radl(radl_data)
        vm = VirtualMachine(None, "1", None, radl, radl)
        apps = vm.getAppsToInstall()
        self.assertEqual(apps[0].getValue("name"), "java")
        self.assertEqual(apps[0].getValue("version"), "1.9")

        modules = vm.getModulesToInstall()
        self.assertEqual(modules[0], "grycap.clues")

    def test_get_remote_port(self):
        radl_data = """
            system test (
            disk.0.os.name = 'linux'
            )"""
        radl = radl_parse.parse_radl(radl_data)
        vm = VirtualMachine(None, "1", None, radl, radl)
        port = vm.getRemoteAccessPort()
        self.assertEqual(port, 22)

        radl_data = """
            network net1 (outbound = 'yes' and
                          outports = '1022-22')
            system test (
            net_interface.0.connection = 'net1' and
            disk.0.os.name = 'linux'
            )"""
        radl = radl_parse.parse_radl(radl_data)
        vm = VirtualMachine(None, "1", None, radl, radl)
        port = vm.getRemoteAccessPort()
        self.assertEqual(port, 1022)

        radl_data = """
            system test (
            disk.0.os.name = 'windows'
            )"""
        radl = radl_parse.parse_radl(radl_data)
        vm = VirtualMachine(None, "1", None, radl, radl)
        port = vm.getRemoteAccessPort()
        self.assertEqual(port, 5986)

        radl_data = """
            network net1 (outbound = 'yes' and
                          outports = '105986-5986')
            system test (
            net_interface.0.connection = 'net1' and
            disk.0.os.name = 'windows'
            )"""
        radl = radl_parse.parse_radl(radl_data)
        vm = VirtualMachine(None, "1", None, radl, radl)
        port = vm.getRemoteAccessPort()
        self.assertEqual(port, 105986)

    @patch("IM.VirtualMachine.VirtualMachine.get_ssh_ansible_master")
    @patch("tempfile.mkdtemp")
    def test_get_ctxt_log(self, mkdtemp, get_ssh_ansible_master):
        ssh = MagicMock()
        get_ssh_ansible_master.return_value = ssh
        mkdtemp.return_value = "/tmp/test_get_ctxt"
        os.mkdir("/tmp/test_get_ctxt")
        with open('/tmp/test_get_ctxt/ctxt_agent.log', 'w+') as f:
            f.write("cont_log")

        vm = VirtualMachine(None, "1", None, None, None)
        cont_log = vm.get_ctxt_log("", delete=True)
        self.assertEqual(cont_log, "cont_log")

    @patch("IM.VirtualMachine.VirtualMachine.get_ssh_ansible_master")
    @patch("tempfile.mkdtemp")
    def test_get_ctxt_output(self, mkdtemp, get_ssh_ansible_master):
        ssh = MagicMock()
        get_ssh_ansible_master.return_value = ssh
        mkdtemp.return_value = "/tmp/test_get_ctxt"
        os.mkdir("/tmp/test_get_ctxt")
        with open('/tmp/test_get_ctxt/ctxt_agent.out', 'w+') as f:
            f.write('{"OK": true, "CHANGE_CREDS": true}')

        radl_data = """
            system test (
            disk.0.os.credentials.username = 'user' and
            disk.0.os.credentials.password = 'pass' and
            disk.0.os.credentials.new.password = 'newpass'
            )"""
        radl = radl_parse.parse_radl(radl_data)
        inf = MagicMock()
        inf.id = "1"
        vm = VirtualMachine(inf, "1", None, radl, radl)
        cont_out = vm.get_ctxt_output("", delete=True)
        self.assertEqual(cont_out, "Contextualization agent output processed successfully")
        self.assertEqual(vm.info.systems[0].getCredentialValues(), ('user', 'newpass', None, None))


if __name__ == '__main__':
    unittest.main()
