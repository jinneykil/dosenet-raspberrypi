import time
import traceback

from globalvalues import RPI
if RPI:
    import RPi.GPIO as GPIO

from auxiliaries import Config, PublicKey, LED
from globalvalues import POWER_LED_PIN, NETWORK_LED_PIN
from auxiliaries import datetime_from_epoch, set_verbosity
from sender import ServerSender
from data_handler_d3s import Data_Handler_D3S

from globalvalues import DEFAULT_CONFIG, DEFAULT_PUBLICKEY, DEFAULT_LOGFILE_D3S
from globalvalues import DEFAULT_HOSTNAME, DEFAULT_UDP_PORT, DEFAULT_TCP_PORT
from globalvalues import DEFAULT_SENDER_MODE
from globalvalues import DEFAULT_DATALOG_D3S


import argparse
import kromek
import numpy as np

import time

from globalvalues import DEFAULT_INTERVAL_NORMAL_D3S
from globalvalues import DEFAULT_INTERVAL_TEST_D3S

from auxiliaries import set_verbosity

import signal
import sys

def signal_term_handler(signal, frame):
    # If SIGTERM signal is intercepted, the SystemExit exception routines
    #   get run
    print 'Got Sigterm!'
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_term_handler)

class Manager_D3S(object):
    """
    Master object for D3S device operation. 
    
    Prints out spectra for every interval, stores each spectra, and sums the spectra together. 
    
    Interval is in seconds with the default being 30 seconds.
    """
    
    def __init__(self,
                 interval=None,
                 count=0,
                 transport='any', 
                 device='all',
                 log_bytes=False,
                 verbosity=None, 
                 datalog=None,
                 datalogflag=False,
                 test=None,
                 config=None,
                 publickey=None,
                 hostname=DEFAULT_HOSTNAME,
                 port=None,
                 sender_mode=DEFAULT_SENDER_MODE,
                 logfile=None, 
                 log=False,
                 running=False,
                 network_LED_pin=NETWORK_LED_PIN,
                 power_LED_pin=POWER_LED_PIN,
                 ):
    
        self.running = running
        
        self.total = None
        self.lst = None
        self.create_structures = True
        
        self.interval = interval
        self.count = count
        
        self.transport = transport
        self.device = device
        self.log_bytes = log_bytes

        self.datalog = datalog
        self.datalogflag = datalogflag

        self.a_flag()
        self.d_flag()
        self.make_data_log(self.datalog)

        self.test = test
        
        self.handle_input(log, logfile, verbosity, interval, config, publickey)
        
        if RPI:
            self.power_LED = LED(power_LED_pin)
            self.network_LED = LED(network_LED_pin)
            
            self.power_LED.on()
            
        else:
            self.power_LED = None
            self.network_LED = None
        
        self.data_handler = Data_Handler_D3S(
            manager=self,
            verbosity=self.v,
            logfile=self.logfile,
            network_led=self.network_LED)
        self.sender = ServerSender(
            manager=self,
            mode=sender_mode,
            port=port,
            verbosity=self.v,
            logfile=self.logfile,)
        # DEFAULT_UDP_PORT and DEFAULT_TCP_PORT are assigned in sender
        
        self.data_handler.backlog_to_queue()
            
    def a_flag(self):
        """
        Checks if the -a from_argparse is called.
        If it is called, sets the path of the data-log to
        DEFAULT_DATALOG.
        """
        if self.datalogflag:
            self.datalog = DEFAULT_DATALOG_D3S

    def d_flag(self):
        """
        Checks if the -d from_argparse is called.
        If it is called, sets datalogflag to True.
        """
        if self.datalog:
            self.datalogflag = True

    def make_data_log(self, file):
        if self.datalogflag:
            with open(file, 'a') as f:
                pass
    
    def handle_input(self, log, logfile, verbosity, interval, config, publickey):
        """
        Sets up logging, verbosity, interval, config, and publickey
        """
        
        # resolve logging defaults
        if log and logfile is None:
            # use default file if logging is enabled
            logfile = DEFAULT_LOGFILE_D3S
        if logfile and not log:
            # enable logging if logfile is specified
            #   (this overrides a log=False input which wouldn't make sense)
            log = True
        if log:
            self.logfile = logfile
        else:
            self.logfile = None        
        
        if verbosity is None:
            verbosity = 1
        self.v = verbosity
        set_verbosity(self, logfile=logfile)
        
        if log:
            self.vprint(1, '')
            self.vprint(1, 'Writing to logfile at {}'.format(self.logfile))
        self.running = True
        
        if interval is None:
            self.vprint(
                2, "No interval given, using interval at 30 seconds")
            interval = DEFAULT_INTERVAL_NORMAL_D3S
        if config is None:
            self.vprint(2, "No config file given, " +
                        "attempting to use default config path")
            config = DEFAULT_CONFIG
        if publickey is None:
            self.vprint(2, "No publickey file given, " +
                        "attempting to use default publickey path")
            publickey = DEFAULT_PUBLICKEY

        self.interval = interval
        
        if config:
            try:
                self.config = Config(config,
                                     verbosity=self.v, logfile=self.logfile)
            except IOError:
                raise IOError(
                    'Unable to open config file {}!'.format(config))
        else:
            self.vprint(
                1, 'WARNING: no config file given. Not posting to server')
            self.config = None

        if publickey:
            try:
                self.publickey = PublicKey(
                    publickey, verbosity=self.v, logfile=self.logfile)
            except IOError:
                raise IOError(
                    'Unable to load publickey file {}!'.format(publickey))
        else:
            self.vprint(
                1, 'WARNING: no public key given. Not posting to server')
            self.publickey = None

    def run(self):
        """
        Main method. Currently also stores and sum the spectra as well. 
        
        Current way to stop is only using a keyboard interrupt.
        """
        
        if self.transport == 'any':
            devs = kromek.discover()
        else:
            devs = kromek.discover(self.transport)
        print 'Discovered %s' % devs
        if len(devs) <= 0:
            return
        
        filtered = []
        
        for dev in devs:
            if self.device == 'all' or dev[0] in self.device:
                filtered.append(dev)
    
        devs = filtered
        if len(devs) <= 0:
            return

        done_devices = set()
        try:    
            while self.running:
                with kromek.Controller(devs, self.interval) as controller:
                    for reading in controller.read():
                        if self.create_structures:
                            self.total = np.array(reading[4])
                            self.lst = np.array([reading[4]])
                            self.create_structures = False
                        else:
                            self.total += np.array(reading[4])
                            self.lst = np.concatenate((self.lst, [np.array(reading[4])]))
                        serial = reading[0]
                        dev_count = reading[1]
                        if serial not in done_devices:
                            this_start, this_end = self.get_interval(
                                time.time() - self.interval)
        
                            self.handle_spectra(this_start, this_end, reading[4])
                        if dev_count >= self.count > 0:
                            done_devices.add(serial)
                            controller.stop_collector(serial)
                        if len(done_devices) >= len(devs):
                            break
        except KeyboardInterrupt:
            self.vprint(1, '\nKeyboardInterrupt: stopping Manager run')
            self.takedown()
        except SystemExit:
            self.vprint(1, '\nSystemExit: taking down Manager')
            self.takedown()
    
    def get_interval(self, start_time):
        """
        Return start and end time for interval, based on given start_time.
        """
        end_time = start_time + self.interval
        return start_time, end_time

    def data_log(self, file, spectra):
        """
        Writes spectra to data-log.
        """
        if self.datalogflag:
            with open(file, 'a') as f:
                f.write('{0}, '.format(spectra))
                self.vprint(2, 'Writing spectra to data log at {}'.format(file))
                
    def handle_spectra(self, this_start, this_end, spectra):
        """
        Get spectra from sensor, display text, send to server.
        """
        self.data_handler.main(
            self.datalog, spectra, this_start, this_end)
            
    def takedown(self): 
        """
        Sets self.running to False and deletes self. Also turns off LEDs
        """
        self.power_LED.off()
        GPIO.cleanup()
        
        self.running = False
        self.data_handler.send_all_to_backlog()
        
        del(self)

    @classmethod
    def from_argparse(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument('--hostname', '-s', default=DEFAULT_HOSTNAME)
        parser.add_argument('--port', '-p', type=int, default=None)
        parser.add_argument('--sender-mode', '-m', type=str, default=DEFAULT_SENDER_MODE, choices=['udp', 'tcp', 'UDP', 'TCP'])
        parser.add_argument('--config', '-c', default=None)
        parser.add_argument('--datalog', '-d', default=None)
        parser.add_argument('--datalogflag', '-a', action='store_true', default=False)
        parser.add_argument('--publickey', '-k', default=None)
        parser.add_argument('--verbosity', '-v', type=int, default=None)
        parser.add_argument('--test', '-t', action='store_true', default=False)        
        parser.add_argument('--transport', '-n', default='any')
        parser.add_argument('--interval', '-i', type=int, default=None)
        parser.add_argument('--count', '-0', dest='count', default=0)
        parser.add_argument('--device', '-e', dest='device', default='all')
        parser.add_argument('--log-bytes', '-b', dest='log_bytes', default=False, action='store_true')
        parser.add_argument('--log', '-l', action='store_true', default=False)
        parser.add_argument('--logfile', '-f', type=str, default=None)
        
        args = parser.parse_args()
        arg_dict = vars(args)
        mgr = Manager_D3S(**arg_dict)
        
        return mgr
    
if __name__ == '__main__':
    mgr = Manager_D3S.from_argparse()
    try:
        mgr.run()
    except:
        if mgr.logfile:
            # print exception info to logfile
            with open(mgr.logfile, 'a') as f:
                traceback.print_exc(15, f)
        # regardless, re-raise the error which will print to stderr
        raise
