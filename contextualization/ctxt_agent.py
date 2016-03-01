#! /usr/bin/env python
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

from optparse import OptionParser
import re
import time
import logging
import logging.config
import sys, subprocess, os
import getpass
import json
import threading
from StringIO import StringIO
import socket

from SSH import SSH, AuthenticationException
from ansible_launcher import AnsibleThread


SSH_WAIT_TIMEOUT = 600
# This value enables to retry the playbooks to avoid some SSH connectivity problems
# The minimum value is 1. This value will be in the data file generated by the ConfManager
PLAYBOOK_RETRIES = 1
INTERNAL_PLAYBOOK_RETRIES = 1

PK_FILE = "/tmp/ansible_key"

def wait_winrm_access(vm):
	"""
	 Test the WinRM access to the VM
	"""
	delay = 10
	wait = 0
	last_tested_private = False
	while wait < SSH_WAIT_TIMEOUT:
		if 'private_ip' in vm and not last_tested_private:
			# First test the private one
			vm_ip = vm['private_ip']
			last_tested_private = True
		else:
			vm_ip = vm['ip']
			last_tested_private = False
		try:
			logger.debug("Testing WinRM access to VM: " + vm_ip)
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			result = sock.connect_ex((vm_ip,5986))
		except:
			logger.exception("Error connecting with WinRM with: " + vm_ip)
			result = -1

		if result == 0:
			vm['ip'] = vm_ip
			return True
		else:
			wait += delay
			time.sleep(delay)
			

def wait_ssh_access(vm):
	"""
	 Test the SSH access to the VM
	"""
	delay = 10
	wait = 0
	success = False
	res = None
	last_tested_private = False
	while wait < SSH_WAIT_TIMEOUT:
		if 'private_ip' in vm and not last_tested_private:
			# First test the private one
			vm_ip = vm['private_ip']
			last_tested_private = True
		else:
			vm_ip = vm['ip']
			last_tested_private = False
		logger.debug("Testing SSH access to VM: " + vm_ip)
		wait += delay
		try:
			ssh_client = SSH(vm_ip, vm['user'], vm['passwd'], vm['private_key'], vm['ssh_port'])
			success = ssh_client.test_connectivity()
			res = 'init'
		except AuthenticationException:
			try_ansible_key = True
			if 'new_passwd' in vm:
				try_ansible_key = False
				# If the process of changing credentials has finished in the VM, we must use the new ones
				logger.debug("Error connecting with SSH with initial credentials with: " + vm_ip + ". Try to use new ones.")
				try:
					ssh_client = SSH(vm_ip, vm['user'], vm['new_passwd'], vm['private_key'], vm['ssh_port'])
					success = ssh_client.test_connectivity()
					res = "new"
				except AuthenticationException:
					try_ansible_key = True
			
			if try_ansible_key:
				# In some very special cases the last two cases fail, so check if the ansible key works 
				logger.debug("Error connecting with SSH with initial credentials with: " + vm_ip + ". Try to ansible_key.")
				try:
					ssh_client = SSH(vm_ip, vm['user'], None, PK_FILE, vm['ssh_port'])
					success = ssh_client.test_connectivity()
					res = 'pk_file'
				except:
					logger.exception("Error connecting with SSH with: " + vm_ip)
					success = False
			
		if success:
			vm['ip'] = vm_ip
			return res
		else:
			time.sleep(delay)
	
	return None

def run_command(command, timeout = None, poll_delay = 5):
	"""
	 Function to run a command
	"""
	try:
		p=subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
		
		if timeout is not None:
			wait = 0
			while p.poll() is None and wait < timeout:
				time.sleep(poll_delay)
				wait += poll_delay

			if p.poll() is None:
				p.kill()
				return "TIMEOUT"

		(out, err) = p.communicate()
		
		if p.returncode!=0:
			return "ERROR: " + err + out
		else:
			return out
	except Exception, ex:
		return "ERROR: Exception msg: " + str(ex)

def wait_thread(thread, output = None):
	"""
	 Wait for a thread to finish
	"""
	thread.join()
	(return_code, hosts_with_errors) = thread.results

	if output:
		if return_code==0:
			logger.info(output)
		else:
			logger.error(output)

	return (return_code==0, hosts_with_errors)

def LaunchAnsiblePlaybook(output, playbook_file, vm, threads, inventory_file, pk_file, retries, change_pass_ok):
	logger.debug('Call Ansible')

	extra_vars = {}
	user = None
	if vm['os'] == "windows":
		gen_pk_file = None
		passwd = vm['passwd']
		if 'new_passwd' in vm and vm['new_passwd'] and change_pass_ok:
			passwd = vm['new_passwd']

		extra_vars['IM_HOST'] = vm['ip']
	else:
		extra_vars['IM_HOST'] = vm['ip']
		passwd = None
		if pk_file:
			gen_pk_file = pk_file
		else:
			if vm['private_key'] and not vm['passwd']:
				gen_pk_file = "/tmp/pk_" + vm['ip'] + ".pem"
				# If the file exists do not create it again
				if not os.path.isfile(gen_pk_file):
					pk_out = open(gen_pk_file, 'w')
					pk_out.write(vm['private_key'])
					pk_out.close()
					os.chmod(gen_pk_file,0400)
			else:
				gen_pk_file = None
				passwd = vm['passwd']
				if 'new_passwd' in vm and vm['new_passwd'] and change_pass_ok:
					passwd = vm['new_passwd']
	
	t = AnsibleThread(output, playbook_file, None, threads, gen_pk_file, passwd, retries, inventory_file, user, extra_vars)
	t.start()
	return t

def changeVMCredentials(vm, pk_file):
	if vm['os'] == "windows":
		#ansible -i hosts -m win_user -a "name=bob password=Password12345 groups=Users" all
		return False

	# Check if we must change user credentials in the VM
	if 'passwd' in vm and vm['passwd'] and 'new_passwd' in vm and vm['new_passwd']:
		logger.info("Changing password to VM: " + vm['ip'])
		private_key = vm['private_key']
		if pk_file:
			private_key = pk_file
		try:
			ssh_client = SSH(vm['ip'], vm['user'], vm['passwd'], private_key, vm['ssh_port'])
			(out, err, code) = ssh_client.execute('sudo bash -c \'echo "' + vm['user'] + ':' + vm['new_passwd'] + '" | /usr/sbin/chpasswd && echo "OK"\' 2> /dev/null')
		except:
			logger.exception("Error changing password to VM: " + vm['ip'] + ".")
			return False
		
		if code == 0:
			vm['passwd'] = vm['new_passwd']
			return True
		else:
			logger.error("Error changing password to VM: " + vm['ip'] + ". " + out + err)
			return False

	if 'new_public_key' in vm and vm['new_public_key'] and 'new_private_key' in vm and vm['new_private_key']:
		logger.info("Changing public key to VM: " + vm['ip'])
		private_key = vm['private_key']
		if pk_file:
			private_key = pk_file
		try:
			ssh_client = SSH(vm['ip'], vm['user'], vm['passwd'], private_key, vm['ssh_port'])
			(out, err, code) = ssh_client.execute('echo ' + vm['new_public_key'] + ' >> .ssh/authorized_keys')
		except:
			logger.exception("Error changing public key to VM: " + vm['ip'] + ".")
			return False
			
		if code != 0:
			logger.error("Error changing public key to VM:: " + vm['ip'] + ". " + out + err)
			return False
		else:
			vm['private_key'] = vm['new_private_key']
			return True

	return False

def removeRequiretty(vm, pk_file):
	if not vm['master']:
		logger.info("Removing requiretty to VM: " + vm['ip'])
		try:
			private_key = vm['private_key']
			if pk_file:
				private_key = pk_file
			ssh_client = SSH(vm['ip'], vm['user'], vm['passwd'], private_key, vm['ssh_port'])
			# Activate tty mode to avoid some problems with sudo in REL
			ssh_client.tty = True
			(stdout, stderr, code) = ssh_client.execute("sudo sed -i 's/.*requiretty$/#Defaults requiretty/' /etc/sudoers")
			logger.debug("OUT: " + stdout + stderr)
			return code == 0
		except:
			logger.exception("Error removing requiretty to VM: " + vm['ip'])
			return False
	else:
		return True

def replace_vm_ip(old_ip, new_ip):
	# Replace the IP with the one that is actually working
	# in the inventory and in the general info file
	filename = conf_data_filename
	with open(filename) as f:
		inventoy_data = f.read().replace(old_ip, new_ip)

	with open(filename, 'w+') as f:
		f.write(inventoy_data)
	
	# in inventory only replace the first item of the line
	filename  = general_conf_data['conf_dir'] + "/hosts"
	with open(filename) as f:
		inventoy_data = ""
		for line in f:
			inventoy_data += re.sub("^%s" % old_ip, new_ip, line)

	with open(filename, 'w+') as f:
		f.write(inventoy_data)

def contextualize_vm(general_conf_data, vm_conf_data):
	res_data = {}
	logger.info('Generate and copy the ssh key')
	
	# If the file exists, do not create it again
	if not os.path.isfile(PK_FILE):
		out = run_command('ssh-keygen -t rsa -C ' + getpass.getuser() + ' -q -N "" -f ' + PK_FILE)
		logger.debug(out)

	# Check that we can SSH access the node
	ctxt_vm = None
	for vm in general_conf_data['vms']:
		if vm['id'] == vm_conf_data['id']:
			ctxt_vm = vm
	
	if not ctxt_vm:
		logger.error("No VM to Contextualize!")
		res_data['OK'] = False
		return res_data
		
	for task in vm_conf_data['tasks']:
		task_ok = False
		num_retries = 0
		while not task_ok and num_retries < PLAYBOOK_RETRIES: 
			num_retries += 1
			logger.info('Launch task: ' + task)
			if ctxt_vm['os'] == "windows":
				playbook = general_conf_data['conf_dir'] + "/" + task + "_task_all_win.yml"
			else:
				playbook = general_conf_data['conf_dir'] + "/" + task + "_task_all.yml"
			inventory_file  = general_conf_data['conf_dir'] + "/hosts"
			
			ansible_thread = None
			if task == "basic":
				# This is always the fist step, so put the SSH test, the requiretty removal and change password here
				for vm in general_conf_data['vms']:
					orig_vm_ip = vm['ip']
					if vm['os'] == "windows":
						logger.info("Waiting WinRM access to VM: " + vm['ip'])
						ssh_res = wait_winrm_access(vm)
					else:
						logger.info("Waiting SSH access to VM: " + vm['ip'])
						ssh_res = wait_ssh_access(vm)
					
					# the IP has changed public for private and we are the master VM
					if orig_vm_ip != vm['ip'] and ctxt_vm['master']:
						# update the ansible inventory  
						logger.info("Changing the IP %s for %s in config files." % (orig_vm_ip, vm['ip']))
						replace_vm_ip(orig_vm_ip, vm['ip'])

					if vm['id'] == vm_conf_data['id']:
						cred_used = ssh_res
					if not ssh_res:
						logger.error("Error Waiting access to VM: " + vm['ip'])
						res_data['SSH_WAIT'] = False
						res_data['OK'] = False
						return res_data
					else:
						res_data['SSH_WAIT'] = True
						logger.info("Remote access to VM: " + vm['ip']+ " Open!")
				
				# The basic task uses the credentials of VM stored in ctxt_vm
				pk_file = None
				if cred_used == "pk_file":
					pk_file = PK_FILE
				
				# First remove requiretty in the node
				if ctxt_vm['os'] != "windows":
					success = removeRequiretty(ctxt_vm, pk_file)
					if success:
						logger.info("Requiretty successfully removed")
					else:
						logger.error("Error removing Requiretty")

				# Check if we must chage user credentials
				# Do not change it on the master. It must be changed only by the ConfManager
				change_creds = False
				if not ctxt_vm['master']:
					change_creds = changeVMCredentials(ctxt_vm, pk_file)
					res_data['CHANGE_CREDS'] = change_creds
				
				if ctxt_vm['os'] != "windows":
					# this step is not needed in windows systems
					ansible_thread = LaunchAnsiblePlaybook(logger, playbook, ctxt_vm, 2, inventory_file, pk_file, INTERNAL_PLAYBOOK_RETRIES, change_creds)
			else:
				# In some strange cases the pk_file disappears. So test it and remake basic recipe
				if ctxt_vm['os'] != "windows":
					success = False
					try:
						ssh_client = SSH(ctxt_vm['ip'], ctxt_vm['user'], None, PK_FILE, ctxt_vm['ssh_port'])
						success = ssh_client.test_connectivity()
					except:
						success = False
		
					if not success:
						logger.warn("Error connecting with SSH using the ansible key with: " + ctxt_vm['ip'] + ". Call the basic playbook again.")
						basic_playbook = general_conf_data['conf_dir'] + "/basic_task_all.yml"
						output_basic = StringIO()
						ansible_thread = LaunchAnsiblePlaybook(output_basic, basic_playbook, ctxt_vm, 2, inventory_file, None, INTERNAL_PLAYBOOK_RETRIES, True)
						ansible_thread.join()
	
				# in the other tasks pk_file can be used
				ansible_thread = LaunchAnsiblePlaybook(logger, playbook, ctxt_vm, 2, inventory_file, PK_FILE, INTERNAL_PLAYBOOK_RETRIES, vm_conf_data['changed_pass'])
			
			if ansible_thread:
				(task_ok, _) = wait_thread(ansible_thread)
			else:
				task_ok = True
			if not task_ok:
				logger.warn("ERROR executing task %s: (%s/%s)" % (task, num_retries, PLAYBOOK_RETRIES))
			else:
				logger.info('Task %s finished successfully' % task)

		res_data[task] = task_ok
		if not task_ok:
			res_data['OK'] = False
			return res_data

	res_data['OK'] = True

	logger.info('Process finished')
	return res_data

if __name__ == "__main__":
	parser = OptionParser(usage="%prog [general_input_file] [vm_input_file]", version="%prog 1.0")
	(options, args) = parser.parse_args()
	
	if len(args) != 2:
		parser.error("Error: Incorrect parameters")
	
	# load json conf data
	conf_data_filename = args[0]
	with open(conf_data_filename) as f:
		general_conf_data = json.load(f)
	with open(args[1]) as f:
		vm_conf_data = json.load(f)
	
	# Root logger: is used by paramiko
	logging.basicConfig(filename=vm_conf_data['remote_dir'] +"/ctxt_agent.log",
			    level=logging.WARNING,
			    #format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
			    format='%(message)s',
			    datefmt='%m-%d-%Y %H:%M:%S')
	# ctxt_agent logger
	logger = logging.getLogger('ctxt_agent')
	logger.setLevel(logging.DEBUG)

	MAX_SSH_WAIT = 60

	if 'playbook_retries' in general_conf_data:
		PLAYBOOK_RETRIES = general_conf_data['playbook_retries']
		
	PK_FILE = general_conf_data['conf_dir'] + "/" + "ansible_key"

	success = False
	res_data = contextualize_vm(general_conf_data, vm_conf_data)
	
	ctxt_out = open(vm_conf_data['remote_dir'] +"/ctxt_agent.out", 'w')
	json.dump(res_data, ctxt_out, indent=2)
	ctxt_out.close()

	if res_data['OK']:
		sys.exit(0)
	else:
		sys.exit(1)
