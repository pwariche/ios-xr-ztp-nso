#!/usr/bin/env python


# since /pkg/bin is not in default PYTHONPATH, the following 
# two lines are necessary to be able to use the ztp_helper.py
# library on the box

import sys
sys.path.append("/pkg/bin/")

from ztp_helper import ZtpHelpers
import os, subprocess, shutil
import re, datetime, json, tempfile, time
import urllib2
import urllib
import base64

ROOT_USER = "cisco"
ROOT_USER_SECRET = "$1$wPyA$bKMN4x5OUqFNDeP5NvJyd0" 
ROOT_USER_PASSWD = "cisco"

SERVER_URL = "http://172.30.0.22:80/"
SERVER_URL_PACKAGES = SERVER_URL + "ncs5000/6.2.25/"
SERVER_URL_SCRIPTS = SERVER_URL + "scripts/"
SERVER_URL_CONFIGS = SERVER_URL + "configs/"
CONFIG_FILES_MAP = {"FOC1947R143" : "ncs-5001-1.config"}

K9SEC_PACKAGE = "ncs5k-k9sec-3.2.0.0-r6225.x86_64.rpm"
MGBL_PACKAGE = "ncs5k-mgbl-3.0.0.0-r6225.x86_64.rpm"
SYSLOG_SERVER = "172.30.0.22"
SYSLOG_PORT = 514
SYSLOG_LOCAL_FILE = "/root/ztp_python.log"

NSO_SERVER = "172.30.0.29"
BASE_URI = "http://" + NSO_SERVER + ":8080/api/running"
NSO_USER = 'admin'
NSO_PASSWD = 'admin'


myDevice = {
    "device": {
        "name": "XXXX",
        "address": "XXXX",
        "port": 22,
        "state": {
            "admin-state": "unlocked"
        },
        "authgroup": "ios-xr-default",
        "device-type": {
            "cli": {
              "ned-id": "tailf-ned-cisco-ios-xr-id:cisco-ios-xr"
            }
        }
    }
}

class ZtpFunctions(ZtpHelpers):

   def set_root_user(self):
        """User defined method in Child Class
           Sets the root user for IOS-XR during ZTP
           Leverages xrapply() method in ZtpHelpers Class.
           :return: Return a dictionary with status and output
                    { 'status': 'error/success', 'output': 'output from xrapply' }
           :rtype: dict
        """
        config = """ !
                     username %s 
                     group root-lr
                     group cisco-support
                     secret 5 %s 
                     !
                     end""" % (ROOT_USER, ROOT_USER_SECRET)



        with tempfile.NamedTemporaryFile(delete=True) as f:
            f.write("%s" % config)
            f.flush()
            f.seek(0)
            result = self.xrapply(f.name)

        if result["status"] == "error":
            self.syslogger.info("Failed to apply root user to system %s" % json.dumps(result))
        else:
            self.syslogger.info("Success applying root user configuration to system %s" % json.dumps(result))


   def install_xr_update(self, package_url):
        """ Method to install XR packages through initial download followed
            by local install and cleanup
            Uses install update utility
            :param package_url: Complete URL of the package to be downloaded
                                and installed
            :type package_url: str
            :return: Dictionary specifying success/error and an associated message
                     {'status': 'success/error',
                      'output': 'success/error message',
                      'warning': 'warning if cleanup fails'}
            :rtype: dict
        """

        result = {"status": "error", "output" : "Installation of package  failed!"}

        # First download the package to the /misc/app_host/scratch folder

        output = self.download_file(package_url, destination_folder="/misc/app_host/scratch")

        if output["status"] == "error":
            if self.debug:
                self.logger.debug("Package Download failed, aborting installation process")
            self.syslogger.info("Package Download failed, aborting installation process")

            return result

        elif output["status"] == "success":
            if self.debug:
                self.logger.debug("Package Download complete, starting installation process")

            self.syslogger.info("Package Download complete, starting installation process")

            rpm_name = output["filename"]
            rpm_location = output["folder"]
            rpm_path = os.path.join(rpm_location, rpm_name)

            ## Query the downloaded RPM to figure out the package name
            cmd = 'rpm -qp ' + str(rpm_path)
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            out, err = process.communicate()

            if process.returncode:
                if self.debug:
                    self.logger.debug("Failed to get the Package name from downloaded RPM, aborting installation process")
                self.syslogger.info("Failed to get the Package name from downloaded RPM, aborting installation process")

                result["status"] = "error"
                result["output"] = "Failed to get the package name from RPM %s" % rpm_name

                # Cleanup
                try:
                    os.remove(rpm_path)
                except OSError:
                    result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                return result

            else:
                package_name = out.rstrip()
                if package_name.endswith('.x86_64'):
                    package_name = package_name[:-len('.x86_64')]
                else:
                    result["status"] = "error"
                    result["output"] = "Package name %s does not end with x86_64 for  RPM %s" % (package_name, rpm_name)

                    # Cleanup
                    try:
                        os.remove(rpm_path)
                    except OSError:
                        result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                    return result

                # Now install the package using install update

                install_update = self.xrcmd({"exec_cmd" : "install update source  %s %s" % (rpm_location, rpm_name)})

                if install_update["status"] == "success":
                    t_end = time.time() + 60 * 5
                    while time.time() < t_end:

                        install_active = self.xrcmd({"exec_cmd" : "show install active"})

                        if install_active["status"] == "error":
                            result["status"] = "error"
                            result["output"] = "Failed to fetch output of show install active -Installation of package %s failed" % package_name
                            # Cleanup
                            try:
                                os.remove(rpm_path)
                            except OSError:
                                result["warning"] = "failed to remove RPM from path: "+str(rpm_path)

                            return result

                            break
                        else:
                            # Sleep for 10 seconds before checking again
                            time.sleep(10)
                            if self.debug:
                                self.logger.debug("Waiting for installation of %s package to complete" % package_name)
                            self.syslogger.info("Waiting for installation of %s package to complete" % package_name)

                    if result["status"] == "error":
                        result["output"] =  "Installation of %s package timed out" % package_name
                        # Cleanup
                        try:
                            os.remove(rpm_path)
                        except OSError:
                            result["warning"] = "failed to remove RPM from path: "+str(rpm_path)


                    return result
                else:
                    result["status"] = "error"
                    result["output"] = "Failed to execute install update command for package: %s" % package_name
                    # Cleanup
                    try:
                        os.remove(rpm_path)
                    except OSError:
                        result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                    return result



   def install_xr_add_activate(self, package_url):
        """ Method to install XR packages through initial download followed
            by local install and cleanup
 
            Uses install add+activate utilities
            :param package_url: Complete URL of the package to be downloaded
                                and installed
            :type package_url: str
            :return: Dictionary specifying success/error and an associated message
                     {'status': 'success/error',
                      'output': 'success/error message',
                      'warning': 'warning if cleanup fails'}
            :rtype: dict
        """

        result = {"status": "error", "output" : "Installation of package  failed!"}

        # First download the package to the /misc/app_host/scratch folder

        output = self.download_file(package_url, destination_folder="/misc/app_host/scratch")

        if output["status"] == "error":
            if self.debug:
                self.logger.debug("Package Download failed, aborting installation process")
            self.syslogger.info("Package Download failed, aborting installation process")

            return result

        elif output["status"] == "success":
            if self.debug:
                self.logger.debug("Package Download complete, starting installation process")

            self.syslogger.info("Package Download complete, starting installation process")

            rpm_name = output["filename"]
            rpm_location = output["folder"]
            rpm_path = os.path.join(rpm_location, rpm_name)

            ## Query the downloaded RPM to figure out the package name
            cmd = 'rpm -qp ' + str(rpm_path)
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            out, err = process.communicate()

            if process.returncode:
                if self.debug:
                    self.logger.debug("Failed to get the Package name from downloaded RPM, aborting installation process")
                self.syslogger.info("Failed to get the Package name from downloaded RPM, aborting installation process")

                result["status"] = "error"
                result["output"] = "Failed to get the package name from RPM %s" % rpm_name

                # Cleanup
                try:
                    os.remove(rpm_path)
                except OSError:
                    result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                return result

            else:
                package_name = out.rstrip()
                if package_name.endswith('.x86_64'):
                    package_name = package_name[:-len('.x86_64')]
                else:
                    result["status"] = "error"
                    result["output"] = "Package name %s does not end with x86_64 for  RPM %s" % (package_name, rpm_name)

                    # Cleanup
                    try:
                        os.remove(rpm_path)
                    except OSError:
                        result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                    return result 
                   
                # Run the install add command in XR exec 

                install_add = self.xrcmd({"exec_cmd" : "install add source %s %s" % (rpm_location, rpm_name)})

                if install_add["status"] == "success":
                    t_end = time.time() + 60 * 5
                    while time.time() < t_end: 
                            
                        install_inactive = self.xrcmd({"exec_cmd" : "show install inactive"})
                            
                        if install_inactive["status"] == "error":
                            result["status"] = "error"
                            result["output"] = "Failed to fetch output of show install inactive -Installation of package %s failed" % package_name
                            # Cleanup
                            try:
                                os.remove(rpm_path)
                            except OSError:
                                result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                        
                            return result
                        else:
                            inactive_packages =  install_inactive["output"][1:]
                            if package_name in inactive_packages:
                                self.logger.debug("Install add successful, ready to activate package %s" % (package_name)) 
                                break 
                            else:
                                # Sleep for 10 seconds before checking again
                                time.sleep(10)
                                if self.debug:
                                    self.logger.debug("Waiting for install add of %s package to complete" % package_name)
                                self.syslogger.info("Waiting for install add of  %s package to complete" % package_name)

                else:
                    result["status"] = "error"
                    result["output"] = "Failed to execute install add command for rpm: %s" % rpm_name
                    # Cleanup
                    try:
                        os.remove(rpm_path)
                    except OSError:
                        result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                    return result




                # Now activate the package

                install_activate = self.xrcmd({"exec_cmd" : "install activate %s" % (package_name)})
                
                if install_activate["status"] == "success":
                    t_end = time.time() + 60 * 5
                    while time.time() < t_end:

                        install_active = self.xrcmd({"exec_cmd" : "show install active"})

                        if install_active["status"] == "error":
                            result["status"] = "error"
                            result["output"] = "Failed to fetch output of show install active -Installation of package %s failed" % package_name
                            # Cleanup
                            try:
                                os.remove(rpm_path)
                            except OSError:
                                result["warning"] = "failed to remove RPM from path: "+str(rpm_path)

                            return result

                            break
                        if install_active["status"] == "success":
                            if self.debug:
                                self.logger.debug("Installation of %s package successful" % package_name)
                            self.syslogger.info("Installation of %s package successsful" % package_name)
                            
                            result["status"] = "success"
                            result["output"] = "Installation of %s package successful" % package_name
                            
                            # Cleanup
                            try:
                                os.remove(rpm_path)
                            except OSError:
                                result["warning"] = "failed to remove RPM from path: "+str(rpm_path)

                            break
                        else:
                            # Sleep for 10 seconds before checking again
                            time.sleep(10)
                            if self.debug:
                                self.logger.debug("Waiting for installation of %s package to complete" % package_name)
                            self.syslogger.info("Waiting for installation of %s package to complete" % package_name)

                    if result["status"] == "error":
                        result["output"] =  "Installation of %s package timed out" % package_name
                        # Cleanup
                        try:
                            os.remove(rpm_path)
                        except OSError:
                            result["warning"] = "failed to remove RPM from path: "+str(rpm_path)


                    return result
                else:
                    result["status"] = "error"
                    result["output"] = "Failed to execute install activate command for package: %s" % package_name
                    # Cleanup
                    try:
                        os.remove(rpm_path)
                    except OSError:
                        result["warning"] = "failed to remove RPM from path: "+str(rpm_path)
                    return result



   def xr_install_commit(self, duration=60):
        """User defined method in Child Class
           Issues an "install commit" to make XR packages persistent. 
           This ensures packages remain active post reloads. 
           Leverages xrcmd() method in ZtpHelpers Class.
           Should be executed post call to install_xr_package() from ZtpHelpers.
           Returns error if 'duration' is exceeded during "show install committed"
           check.
           :param duration: Duration for which the script must wait for the active 
                            packages to be committed. 
           :type duration: int
 
           :return: Return a dictionary with status 
                    { 'status': 'error/success' }
           :rtype: dict
        """
        install_commit = self.xrcmd({"exec_cmd" : "install commit"})

        if install_commit["status"] == "error":
            self.syslogger.info("Failed to commit installed packages")
            return {"status" : "error"} 
        else:
            commit_success = False
            t_end = time.time() + duration
            while time.time() < t_end:
                # Check that the install commit was successful
                commit_state = self.xrcmd({"exec_cmd" : "show install committed"})

                if commit_state["status"] == "error":
                    self.syslogger.info("show install committed failed to execute ")
                    return {"status" : "error"} 

                active_state = self.xrcmd({"exec_cmd" : "show install active"})
                if active_state["status"] == "error":
                    self.syslogger.info("show install active failed to execute ")
                    return {"status" : "error"} 

                # Excluding the date (first line) and lines saying Active vs Committed,
                #  the rest of the commit and active state outputs must match

                commit_output = commit_state["output"][1:]
                commit_compare = [x for x in commit_output if "Committed" not in x]

                active_output = active_state["output"][1:]
                active_compare = [x for x in active_output if "Active" not in x]

                if ''.join(commit_compare) == ''.join(active_compare):
                    self.syslogger.info("Install commit successful!")
                    return {"status" : "success"}
                else:
                    self.syslogger.info("Install commit not done yet")
                    time.sleep(10)

            self.syslogger.info("Install commit unsuccessful!")
            return {"status" : "error"} 

   def get_replace_config(self, url=None, caption=None):
        """User defined method in Child Class
           Downloads IOS-XR config from specified 'url'
           and replaces config to the box. 
           Leverages xrreplace() method in ZtpHelpers Class.
           :param url: Complete url for config to be downloaded 
           :type url: str 
           :type caption: str 
           :return: Return a dictionary with status and output
                    { 'status': 'error/success', 'output': 'output from xrreplace/custom error' }
           :rtype: dict
        """

        result = {"status" : "error", "output" : "", "warning" : ""}

        # Download configuration file
        if url is not None:
            download = self.download_file(url, destination_folder="/root/")
        else:
            self.syslogger.info("URL not specified")
            result["output"] = "URL not specified"
            return result

        if download["status"] == "error":
            self.syslogger.info("Config Download failed")
            result["output"] = "Config Download failed"
            return result
 
            
        file_path = os.path.join(result["folder"], result["filename"])
    
        if caption is None:
            caption = "Configuration Applied through ZTP python"

        # Apply Configuration file
        config_replace = xrreplace(result)

        if config_replace["status"] == "error":
            self.syslogger.info("Failed to apply config: Config Apply result = %s" % config_replace["output"])
            result["output"] = config_replace["output"]
            return result


        # Download and config application successful, mark for success

        result["status"] = "success"
        try:
            os.remove(file_path)
        except OSError:
            self.syslogger.info("Failed to remove downloaded config file")
            result["output"] = config_replace["output"]
            result["warning"] = "Failed to remove downloaded config file @ %s" % file_path
        return result


   def run_bash(self, cmd=None):
        """User defined method in Child Class
           Wrapper method for basic subprocess.Popen to execute 
           bash commands on IOS-XR.
           :param cmd: bash command to be executed in XR linux shell. 
           :type cmd: str 
           
           :return: Return a dictionary with status and output
                    { 'status': '0 or non-zero', 
                      'output': 'output from bash cmd' }
           :rtype: dict
        """
        ## In XR the default shell is bash, hence the name
        if cmd is not None:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            out, err = process.communicate()
        else:
            self.syslogger.info("No bash command provided")


        status = process.returncode

        return {"status" : status, "output" : out}

   def nso_rest(self, ressource=None, operation=None, data=None):
        """
        """
        #base64string = base64.encodestring('%s:%s' % (NSO_USER, NSO_PASSWD)).replace('\n', '')
        if data is not None:
          request = urllib2.Request(ressource, data)
        else:
          request = urllib2.Request(ressource)

        request.add_header("Authorization", "Basic %s" % base64.encodestring('%s:%s' % (NSO_USER, NSO_PASSWD)).replace('\n', ''))
        request.add_header('Content-Type', 'application/vnd.yang.data+json')
        request.get_method = lambda: operation
        try:
            response = urllib2.urlopen(request)
        except urllib2.HTTPError,error:
             self.syslogger.info("REST operation error code: " + str(error.code()))
             self.syslogger.info("REST response: " + error.read()) 
        except URLError, error:
             self.syslogger.info("URL error: " + str(error.code()))
        else:
             self.syslogger.info("REST operation status: " + str(response.code))
             self.syslogger.info("REST return data: "  + response.read())
        return {"status": response.code, "output" : response.read()}


if __name__== "__main__":
   ztp_script = ZtpFunctions(syslog_file=SYSLOG_LOCAL_FILE, syslog_server=SYSLOG_SERVER, syslog_port=SYSLOG_PORT)

   ztp_script.syslogger.info("###### Starting ZTP RUN on NCS001 ######")
   
   # Enable verbose debugging to stdout/console. By default it is off
   ztp_script.toggle_debug(1)

   # Change context to XR VRF in the linux shell when needed. Depends on when user changes config to create network namespace.

   # No Config applied yet, so start with global-vrf(default)"
   ztp_script.set_vrf("global-vrf")
   
   # Set the root user first. Always preferable so that the user can manually gain access to the router in case ZTP script aborts.
   ztp_script.set_root_user()
   
   ztp_script.syslogger.info("###### Installing k9sec package ######")
   install_result =  ztp_script.install_xr_add_activate(SERVER_URL_PACKAGES + K9SEC_PACKAGE)

   if install_result["status"] == "error":
       ztp_script.syslogger.info("Failed to install k9sec package")
       sys.exit(1)

   ztp_script.syslogger.info("###### install mgbl package ######")
   install_result = ztp_script.install_xr_add_activate(SERVER_URL_PACKAGES + MGBL_PACKAGE)

   if install_result["status"] == "error":
       ztp_script.syslogger.info("Failed to install mgbl package")
       sys.exit(1)

   # To make sure xr packages remain active posncs-4.5.2-cisco-iosxr-6.3.2.tar.gzt reloads, commit them
   ztp_script.syslogger.info("Committing the installed packages")
   install_commit = ztp_script.xr_install_commit(60)

   if install_commit["status"] == "error":
       ztp_script.syslogger.info("Failed to commit installed packages")
       sys.exit(1)


   # Install crypto keys
   show_pubkey = ztp_script.xrcmd({"exec_cmd" : "show crypto key mypubkey rsa"})

   if show_pubkey["status"] == "success":
       if show_pubkey["output"] == '':
           ztp_script.syslogger.info("No RSA keys present, Creating...")
           ztp_script.xrcmd({"exec_cmd" : "crypto key generate rsa", "prompt_response" : "2048\\n"})
       else:
           ztp_script.syslogger.info("RSA keys already present, Recreating....")
           ztp_script.xrcmd({"exec_cmd" : "crypto key generate rsa", "prompt_response" : "yes\\n 2048\\n"})
   else:
       ztp_script.syslogger.info("Unable to get the status of RSA keys: "+str(show_pubkey["output"]))
       # Not quitting the script because of this failure


   serial_cmd = "dmidecode | grep -m 1 \"Serial Number\" | awk  \'{print $3}\'"
   serial_number = ztp_script.run_bash(serial_cmd)

   CONFIG_FILE= CONFIG_FILES_MAP[serial_number["output"].rstrip()]

             
   # Download Config with Mgmt vrfs
   output = ztp_script.download_file(SERVER_URL_CONFIGS + CONFIG_FILE, destination_folder="/root/") 

   if output["status"] == "error":
       ztp_script.syslogger.info("Config Download failed, Abort!")
       sys.exit(1)

   ztp_script.syslogger.info("Replacing system config with the downloaded config")
   # Replace existing config with downloaded config file 
   config_apply = ztp_script.xrreplace("/root/" + CONFIG_FILE)

   if config_apply["status"] == "error":
       ztp_script.syslogger.info("Failed to replace existing config")
       ztp_script.syslogger.info("Config Apply result = %s" % config_apply["output"]) 
       try:
           os.remove("/root/" + CONFIG_FILE)
       except OSError:
           ztp_script.syslogger.info("Failed to remove downloaded config file")

   # VRFs on Mgmt interface are configured by user. Use the set_vrf helper method to set proper
   # context before continuing. 
   # Syslog and download operations are covered by the set vrf utility by default.
   # For any other shell commands that utilize the network, 
   # change context to vrf using `ip netns exec <vrf>` before the command

   ztp_script.set_vrf("mgmt")
   ztp_script.syslogger.info("###### Changed context to user specified VRF based on config ######")
   ztp_script.syslogger.info("Base config applied successfully")
   ztp_script.syslogger.info("Config Apply result = %s" % config_apply["output"])
   
   # Need to find a better way to do this env var HOSTNAME is unchanged within ZTP context
   show_hostname = ztp_script.xrcmd({"exec_cmd" : "show run | inc hostname"})
   hostname = str.split(show_hostname['output'][0])[1]

   show_mgmt_ip = ztp_script.xrcmd({"exec_cmd" : "show ipv4 int MgmtEth0/RP0/CPU0/0 brief | inc MgmtEth0/RP0/CPU0/0"})
   mgmt_ip=str.split(show_mgmt_ip['output'][0])[1]

   myDevice["device"]["name"] = hostname
   myDevice["device"]["address"] = mgmt_ip

   # Pushing the device profile to NSO
   ztp_script.syslogger.info("###### Start provisioning device to NSO server ######")
   ztp_script.syslogger.info("###### Pushing Device Profile ######")
   ztp_script.nso_rest(BASE_URI + '/devices/device/' + hostname, 'PUT', json.dumps(myDevice))
   ztp_script.syslogger.info("###### Pushing RSA key ######")
   ztp_script.nso_rest(BASE_URI + '/devices/device/' + hostname + '/ssh/_operations/fetch-host-keys/', 'POST')
   ztp_script.syslogger.info("###### Syncing configuration ######")
   ztp_script.nso_rest(BASE_URI + '/devices/device/' + hostname + '/_operations/sync-from', 'POST')
   
ztp_script.syslogger.info("ZTP complete!")
sys.exit(0)
