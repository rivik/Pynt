#!/usr/bin/env python
# -*- coding: utf-8 -*-

# built-in modules
import logging
import sys
import optparse
import os.path
# local modules
import pynt
import pynt.elements
import pynt.xmlns
import pynt.input
# input/output modules
import pynt.input.serial
import pynt.output.serial
import pynt.output.debug
import pynt.output.manualrdf
import pynt.output.dot
import pynt.input.usernames
import pynt.input.cisco

import pynt.logger
import ConfigParser
from subprocess import call

def GetDefaultDir(dir):
    # default is 'ndl/<dir>/' if it exists, otherwise './'.
    if os.path.exists(dir):
        return dir
    elif os.path.exists('../%s' % dir):  # and os.getcwd().endswith("apps")
        return '../%s' % dir
    elif os.path.exists(os.path.join(os.path.dirname(os.path.realpath(pynt.__file__)), '..', dir)):
        return os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(pynt.__file__)), '..', dir))
    else:
        return '.'

def GetDefaultOutputDir():
    return GetDefaultDir('output')

def GetOptions(argv=None):
    """
    Parse command line arguments.
    """
    if argv is None:
        # allow user to override argv in interactive python interpreter
        argv = sys.argv
    parser = optparse.OptionParser(conflict_handler="resolve")
    # standard option: -h and --help to display these options    
    parser.add_option("-c", "--config", dest="configfile", action="store", metavar="FILE", 
                      help="Device configuration file to read username, password, etc.", default="devices.conf")
    parser.add_option("-o", "--output", dest="outputdir", action="store", type="string", metavar="PATH", 
                      help="The directory to store the output files", default=GetDefaultOutputDir())
    parser.add_option("-l", "--iolog", dest="iologfile", action="store", type="string", metavar="PATH", 
                      help="The file to log raw device I/O communication", default=None)
    parser.add_option("-p", "--port", dest="port", action="store", type="int", 
                      help="The network port to listen to or connect to", default=None)
    parser.add_option("-u", "--username", dest="username", action="store", type="string", 
                      help="The username to log in to the device", default=None)
    parser.add_option("--password", dest="password", action="store", type="string", 
                      help="The password to log in to the device", default=None)
    parser.add_option("-q", "--quiet", dest="quietness", action="count", default=0, 
                      help="Quiet output (multiple -q makes it even more silent)")
    parser.add_option("-v", "--verbose", dest="verbosity", action="count", default=0, 
                      help="Verbose output (multiple -v makes it even chattier)")
    parser.add_option("-s", "--simulate", dest="simulate", action="store", default=None,
                      help="Read information not from device, but from file. Valid options are 'pickle', 'command' and 'offline'")
    parser.add_option("-i","--input", dest="inputdir", action="store", type="string", metavar="PATH",
                      help="Directory to read the simulated data from.", default=GetDefaultDir("rawdata"))
    (options, args) = parser.parse_args(args=argv[1:])
    options.verbosity -= options.quietness
    return (options, args)

class CiscoReader(object):
    def __init__(self):
        self.fetcherclass=pynt.input.cisco.CiscoFetcher
        self.options = None
        self.args = None
        self.devices_conf = None

    def processDevice(self, hostname):
        try:
            identifier = self.devices_conf.get(hostname, "identifier")
        except:
            identifier = None
        if not identifier:
            identifier = hostname
        
        pynt.logger.SetLogLevel(self.options.verbosity)
        logger = logging.getLogger()

        errorfile  = os.path.join(self.options.outputdir, "%s-error.log"      % identifier)  # log of errors
        serialfile = os.path.join(self.options.outputdir, "%s-serial.pickle"  % identifier)  # memory dump
        debugfile  = os.path.join(self.options.outputdir, "%s-debug.txt"      % identifier)  # human readable memory dump
        ndl24file  = os.path.join(self.options.outputdir, "%s-config.rdf"     % identifier)  # All information in latest NDL
        staticfile = os.path.join(self.options.outputdir, "%s-interfaces.rdf" % identifier)  # Static interface configuration in NDL (no configuration info)
        devdotfile = os.path.join(self.options.outputdir, "%s-device.dot"     % identifier)  # Graph with vertices for devices
        ifdotfile  = os.path.join(self.options.outputdir, "%s-interface.dot"  % identifier)  # Graph with vertices for interfaces
        iologfile  = self.options.iologfile                # file to log raw I/O communications with devices
        passwdfile = self.options.configfile               # file with usernames and passwords
        errorlog = pynt.logger.Logger(errorfile, verbosity=self.options.verbosity)
        inputfilename = os.path.join(self.options.inputdir, hostname) 
        try:
            if self.options.simulate in ["pickle", "memory"]:
                if inputfilename:
                    fetcher = pynt.input.serial.SerialInput(inputfilename)
                else:
                    fetcher = pynt.input.serial.SerialInput(serialfile)
            else:
                fetcher = self.fetcherclass(hostname, identifier=identifier)
                if self.options.simulate in ["command"]:
                    logger.log(25, "Performing simulated query on %s" % hostname)
                    if inputfilename:
                        fetcher.setSourceFile(inputfilename)
                    else:
                        fetcher.setSourceFile(iologfile)
                else:
                    logger.log(25, "Performing live query on %s" % hostname)
                    fetcher.setSourceHost(hostname, port=self.options.port)
                userpwd = pynt.input.usernames.GetLoginSettings(hostname, self.options.username, self.options.password, passwdfile)
                fetcher.io.setLoginCredentials(**userpwd)
                if iologfile:
                    fetcher.io.setLogFile(iologfile)

            # fetches data from device and returns object structure.
            # The subject is something that can be passed on to BaseOutput.output();
            # Typically a Device object or namespace.
            subject = fetcher.getSubject()

#            if not self.options.simulate:
#                out = pynt.output.serial.SerialOutput(serialfile)
#                out.output(subject)
#
#            out = pynt.output.debug.DebugOutput(debugfile)
#            out.output(subject)
#
#            out = pynt.output.manualrdf.RDFOutput(ndl24file)
#            out.setMetaData("description", 'Configuration of the %s' % subject.getName())            
#            out.output(subject)
#
#            out.setOutputFile(staticfile)
#            out.setPrintConfigured(False)
#            out.setMetaData("description", 'Configuration of the %s' % subject.getName())            
#            out.output(subject)
#
#            out = pynt.output.dot.DeviceGraphOutput(devdotfile)
#            out.output(subject)
#
#            out = pynt.output.dot.InterfaceGraphOutput(ifdotfile)
#            out.output(subject)

        except:  # *any* kind of exception, including user-interupts, etc.
            # the write functions are atomic, so those will be fine when an exception occurs
            errorlog.logException()
            (exceptionclass, exception, traceback) = sys.exc_info()
            logger.exception("")

        # We check if an error occurred
        # if so, we do nothing, and keep the existing files. Those should still be valid.
        # However, if we previously also had errors, this is probably more fundamental.
        # In that case, we replace the -cache file with the -static file, effectively
        # removing all dynamic data from the RDF files.
        if errorlog.getCurErrorCount() and errorlog.getPrevErrorCount():
            logger.info("Two errors in a row. Overwriting %s with %s" % (ndl24file, staticfile))
            try:
                pynt.output.CopyFile(staticfile, ndl24file)
            except IOError:
                pass
    
    def start(self, argv=None):
        """
        main() function. Parse command line arguments, fetch information from a device, 
        parsing it into a memory structure (specified by pynt.elements) and 
        write that to files in multiple formats
        """
        (self.options, self.args) = GetOptions(argv)
        
        self.devices_conf = ConfigParser.ConfigParser()
        self.devices_conf.read(self.options.configfile)        
        
        ndl24file  = os.path.join(self.options.outputdir, "devices.rdf")  # All information in latest NDL
        devdotfile = os.path.join(self.options.outputdir, "devices.dot")  # Graph with vertices for devices
        ifdotfile  = os.path.join(self.options.outputdir, "interfaces.dot")  # Graph with vertices for interfaces
        devpngfile = os.path.join(self.options.outputdir, "devices.png")
        ifpngfile = os.path.join(self.options.outputdir, "interfaces.png")        
        
        for hostname in self.devices_conf.sections():
            self.processDevice(hostname)        
        
        out = pynt.output.manualrdf.RDFOutput(ndl24file)
        out.output()
        
        out = pynt.output.dot.DeviceGraphOutput(devdotfile)
        out.output()
        
        out = pynt.output.dot.InterfaceGraphOutput(ifdotfile)
        out.output()
        
        call("dot -Tpng -o %s %s 2>/dev/null" % (devpngfile, devdotfile), shell=True)
        call("fdp -Tpng -o %s %s 2>/dev/null" % (ifpngfile, ifdotfile), shell=True)

if __name__ == '__main__':
    reader = CiscoReader()
    reader.start(sys.argv)
