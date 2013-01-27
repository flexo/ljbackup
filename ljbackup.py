import os
import sys
import time
import json
import getpass
import hashlib
import xmlrpclib

class LJBackup(object):
    clientversion = 'Python/FlexoLJBackup/0.0.1'

    def __init__(self, username, password, server='http://www.livejournal.com/interface/xmlrpc', dumpdir='ljbackup'):
        self.username = username
        self.password = password
        self.lj = xmlrpclib.ServerProxy(server).LJ.XMLRPC
        self.dumpdir = os.path.abspath(dumpdir)
        self.challenge_expires = 0
        self.challenge = None
        self.challenge_response = None
        self.time_offset = 0

    def _check_auth(self):
        """Check whether authentication details are still valid.
        Re-authenticate if they are not.
        """
        now = time.time()
        if now + self.time_offset > self.challenge_expires:
            resp = self.lj.getchallenge()
            self.challenge = resp['challenge']
            self.challenge_expires = resp['expire_time']
            self.time_offset = resp['server_time'] - now
            self.challenge_response = hashlib.md5(
                self.challenge + hashlib.md5(self.password).hexdigest()
            ).hexdigest()

    def _login(self):
        """Log into Livejournal. Returns personal data."""
        self._check_auth()
        resp = self.lj.login(dict(
            username=self.username,
            auth_method='challenge',
            auth_challenge=self.challenge,
            auth_response=self.challenge_response,
            clientversion=self.clientversion,
        ))
        return resp

    def _write(self, data, *path):
        """Write out Python data (as JSON) to the path given."""
        strdata = json.dumps(data)
        filepath = os.path.join(*((self.dumpdir, self.username) + path))
        filedir = os.path.dirname(filepath)
        if not os.path.isdir(filedir):
            # create the file's containing directory, if it doesn't exist.
            os.makedirs(filedir)
        if os.path.exists(filepath):
            # only write out file if it's actually changed.
            md5data = hashlib.md5(strdata).digest()
            with open(filepath, 'rb') as f:
                md5file = hashlib.md5(f.read()).digest()
            if md5data != md5file:
                open(filepath, 'wb').write(strdata)
        else:
            open(filepath, 'wb').write(strdata)

    def __call__(self):
        """Main synchronisation routine. Write out all new or updated files."""
        self.user = self._login()
        if not os.path.exists(self.dumpdir):
            try:
                os.mkdir(self.dumpdir)
            except EnvironmentError, e:
                raise
        self._write(self.user, 'user.json')
        

if __name__ == '__main__':
    username = sys.argv[1]
    password = getpass.getpass('Livejournal password: ')
    ljbackup = LJBackup(username, password)
    print "Commencing Backup of user '%s' to %s" % (username, ljbackup.dumpdir)
    ljbackup()
    print "Done"

