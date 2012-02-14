# -*- coding: utf-8 -*-
"""The cisco module contains a parsers which retrieves information from a
cisco ios device using the command line interface"""

# builtin modules
import os
import logging
# local modules
import pynt.protocols.cli
import pynt.elements
import pynt.xmlns
import pynt.input

import pynt.technologies.ethernet     # defines FiberInterface class
import pynt.technologies.ip
import pynt.technologies.tdm
import pynt.technologies.wdm
import pynt.technologies.copper

import re

class CiscoFetcher(pynt.input.BaseDeviceFetcher):
    """
    Fetches information from a cisco ios device using ssh or file input
    Note that self.identifier must be the same as cisco Device ID
    Prompt is the first part of Device ID + '>'
    Hosname is just domain or file name
    
    Example:
    hostname: c65m3-25.jscc.ru
    identifier: C65M3.jscc.ru
    prompt: C65M3>
    """
    def __init__(self, hostname, identifier):
        nsuri = self.deviceIdToNsuri(identifier)
        # set prompt before BaseDevice init (see setSource)
        self.prompt = identifier.split(".")[0]+">"        
        pynt.input.BaseDeviceFetcher.__init__(self, hostname, identifier, nsuri)
        self.subjectClass    = pynt.technologies.ethernet.EthernetDevice
        
        self.iface_re = re.compile(r"^\s*([a-zA-Z]{,2})[a-zA-Z]*(\d+/?\d*\.?\d*)\s*$")
        self.device_id_re = re.compile(r"^Device ID: (\S+.*\S+)\s*$")
        self.iface_port_re = re.compile(r"^Interface: (\S+),  Port ID \(outgoing port\): (\S+)\s*$")
    
    def setSourceHost(self, hostname, port=None):
        self.io = pynt.protocols.cli.SSHInput(hostname=hostname, port=port)
        self.io.setDefaultTimeout(30)
        self.io.setPrompt(self.prompt)
    
    def setSourceFile(self, filename):
        self.io = pynt.protocols.cli.CLIEmulatorInput(filename=filename)        
        self.io.setPrompt(self.prompt)
    
    def command(self, command, skipStartLines=0, lastSkipLineRe=None, skipEndLines=0):
        resultLines = self.io.command(command)
        return pynt.protocols.cli.ParseCLILines(resultLines, skipStartLines=skipStartLines, lastSkipLineRe=lastSkipLineRe, skipEndLines=skipEndLines)
    
    def retrieve(self):
        # get information from device        
        self.command("terminal length 0")   # turn off interactive shell
        self.command("terminal width 0")
        interfacelines   = self.command('show interfaces description', skipStartLines=1)
        vlanlines        = self.command('show vlan brief', skipStartLines=3)
        neighborlines = self.command('show cdp neighbors detail')
        
        self.parseInterfaces(interfacelines)    # sets subject.interfaces
        self.parseVlans(vlanlines)              # sets subject.vlans
        self.parseNeighbors(neighborlines)
        #self.addLogicalMACInterfaces()
        #self.parseInterfaceDetails(interfacedetails)        
    
    def parseInterfaces(self, interfaceLines):
        """
        Parses the Interface string and seperates the different interfaces
        Returns a list of interface objects.
        """
        for line in interfaceLines:
            self.parseInterfaceLine(line)
        return len(interfaceLines)
    
    def deviceIdToNsuri(self, device_id):
        return "%s#" % device_id
    
    def splitIface(self, iface):
        m = self.iface_re.match(iface)
        if m and (m.group(1) or m.group(2)):
            return (m.group(1)+m.group(2), m.group(1), m.group(2))
        else:
            raise pynt.input.ParsingException("The interface name is '%s', which is not in the expected Prefix0/0.0 format." % iface)            
    
    def parseInterfaceLine(self, interfaceString):
        "Parses one Interface line and returns an interface object"
        # InterfaceString looks like:
        # Interface                      Status         Protocol Description
        # Vl1                            admin down     down     
        # Vl10                           up             up       RASNET-ETH-BB       
        # Gi2/1                          up             up       eth0
        ifname      = interfaceString[0:31].rstrip()
        line_status = interfaceString[31:46].rstrip() # "up", "admin down"        
        protocol_status = interfaceString[46:55].rstrip() # "up", "down"
        description = interfaceString[55:].rstrip()
        
        result = False  # return True if a new interface or vlan object was created
        if ifname == "":  # skip empty lines
            return False
        
        try:
            ifnamesplit = self.splitIface(ifname) # e.g. "TenGigabitEthernet4/1" => ["Te","4/1"]
        except:
            raise
        (iface_id, iface_prefix, iface_num) = ifnamesplit 
        if (iface_prefix in ["Fa", "Gi", "Te"]):                        
            interface = self.subject.getCreateNativeInterface(iface_id)  # create Interface object or return existing one
            interface.setName(iface_id)
            result = True
            interface.setPrefix(iface_prefix)
            
            if description:
                interface.setDescription(description)            
            if (line_status in ["admin down", "down"]):
                interface.setAdminStatus("down");
            elif (line_status in ["up"]):
                interface.setAdminStatus("up");
            else:
                raise pynt.input.ParsingException("Unkown line/admin status '%s' of interface %s" % (line_status, iface_id))
            if (line_status == "up"):
                # If adminstatus is down, the link status is not measured and always "down", even if light is received
                if (protocol_status in ["up", "down"]):
                    interface.setLinkStatus(protocol_status);                
                else:
                    raise pynt.input.ParsingException("Unkown link/protocol status '%s' of interface %s" % (protocol_status, iface_id))
        elif (iface_prefix in ["Vl"]):
            vlan = self.subject.getCreateVlan(iface_num)
            result = True
            if (line_status in ["admin down", "down"]):
                vlan.setAdminStatus("down");
            elif (line_status in ["up"]):
                vlan.setAdminStatus("up");
            else:
                raise pynt.input.ParsingException("Unkown line/admin status '%s' of interface %s" % (line_status, iface_id))
            
            # We're currently not storing the "link status"; this is always up, and doesn't seem to have a real meaning            
            if description:
                vlan.setDescription(description)
        #else:            
        #    raise pynt.input.ParsingException("Skipping unknown interface '%s'" % ifname)
        return result
    
    def parseVlans(self, vlanlines):
        """
        Parses the VLAN's and assign vlan tagged/untagged interface to port.
        Returns the number of detected vlans.
        """
        vlancount = 0;
        for line in vlanlines:
            # vlanlines looks like:
            # VLAN Name                             Status    Ports
            # ---- -------------------------------- --------- -------------------------------
            # 1    default                          active    Gi1/46, Te8/2, Te8/3, Te8/4
            
            vlanid = line[0:5].rstrip()   # integer
            name = line[5:38].rstrip()
            adminstatus = line[38:48].rstrip()  # "active", "inactive"
            ports = re.sub("\s+", "", line[48:])    # e.g. "Gi1/46,Te8/2,Te8/3,Te8/4"
            if (vlanid):
                # new line with new VLAN
                if not vlanid.isdigit():
                    raise pynt.input.ParsingException("Expected a VLAN ID, but %s is not a number in '%s'" % (vlanid, line))
                vlan = self.subject.getCreateVlan(int(vlanid))
                vlancount += 1
            if not vlan:
                raise pynt.input.ParsingException("Expected the first line of vlan list to start with a VLAN ID, but got '%s'" % (line))
            if (adminstatus in ["active", "inactive"]):
                vlan.setAdminStatus(adminstatus)
            # elif adminstatus:
            #    raise pynt.input.ParsingException("Skipping unknown adminstatus '%s' of VLAN %s" % (adminstatus, vlanid))
            vlan.setName(name)
            for iface_id in ports.split(','):
                if iface_id == '':
                    continue
                try:
                    self.splitIface(iface_id) # check weither iface_id is cisco iface 
                except:
                    raise
                interface = self.subject.getCreateNativeInterface(iface_id)
                if (vlanid == 1):
                    self.subject.AddUntaggedInterface(vlan, interface)
                else:
                    self.subject.AddTaggedInterface(vlan, interface)                
        return vlancount
    
    def parseNeighbors(self, neighborlines):
        """
        Parses the VLAN's and assign vlan tagged/untagged interface to port.
        Returns the number of detected vlans.
        """
        device_id = None
        local_iface_id = None
        remote_iface_id = None
        state = "skip"
        for line in neighborlines:
            # -------------------------
            # Device ID: C65M4.jscc.ru
            # Entry address(es): 
            #  IP address: 192.168.79.1
            # Platform: cisco WS-C6513,  Capabilities: Router Switch IGMP 
            # Interface: TenGigabitEthernet3/4,  Port ID (outgoing port): TenGigabitEthernet9/2
            if line == "-------------------------":
                device_id = None
                local_iface_id = None
                remote_iface_id = None
                state = "search"
                continue
            if state == "skip":
                continue
            
            if not device_id:
                m = self.device_id_re.match(line)
                if m:
                    device_id = m.group(1)
                    if not device_id:
                        raise pynt.input.ParsingException("Bad Device ID in line '%s'" % (line)) 
            elif not local_iface_id or not remote_iface_id:
                m = self.iface_port_re.match(line)
                if m:
                    (local_iface_id, remote_iface_id) = m.group(1,2)
                    try:
                        local_iface_id = self.splitIface(local_iface_id)[0]
                        remote_iface_id = self.splitIface(remote_iface_id)[0]
                    except:
                        raise
            
            if device_id and local_iface_id and remote_iface_id:
                ns = pynt.xmlns.GetCreateNamespace(self.deviceIdToNsuri(device_id))
                device = pynt.xmlns.GetCreateRDFObject(identifier=device_id,
                        namespace=ns, klass=self.subjectClass)
                local_iface = self.subject.getCreateNativeInterface(local_iface_id)
                remote_iface = device.getCreateNativeInterface(remote_iface_id)
                
                local_iface.addConnectedInterface(remote_iface)
                state = "skip"
            