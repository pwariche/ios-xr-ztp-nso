This example illustrate the possibility to provision a Cisco NCS device running IOS-XR into Cisco Network Service Orchestrator (NSO) using REST.
Upon Bootup, the device will be updated using iPXE and will bootstrap into the image defined in the ipxe script, Once the device is rebooted, it will configure itself using the Zero Touch Provisioning (ZTP) mechanism of IOS-XR
The dhcp directory contains example of isc-dhcp-server configuration that can be used
The scripts directory contains iPXE and ZTP scripts used to provision the device from day-0
The config directory contains example of initial configuration used by ZTP.

