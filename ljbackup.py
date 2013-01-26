import sys
import time
import getpass
import hashlib
import xmlrpclib

class LJBackup(object):
    clientversion = 'Python/FlexoLJBackup/0.0.1'

    def __init__(self, username, password, server='http://www.livejournal.com/interface/xmlrpc'):
        self.username = username
        self.password = password
        self.lj = xmlrpclib.ServerProxy(server).LJ.XMLRPC
        self.challenge_expires = 0
        self.challenge = None
        self.challenge_response = None
        self.time_offset = 0
        self.login()

    def check_auth(self):
        now = time.time()
        if now + self.time_offset > self.challenge_expires:
            resp = self.lj.getchallenge()
            self.challenge = resp['challenge']
            self.challenge_expires = resp['expire_time']
            self.time_offset = resp['server_time'] - now
            self.challenge_response = hashlib.md5(
                self.challenge + hashlib.md5(self.password).hexdigest()
            ).hexdigest()

    def login(self):
        self.check_auth()
        resp = self.lj.login(dict(
            username=self.username,
            auth_method='challenge',
            auth_challenge=self.challenge,
            auth_response=self.challenge_response,
            clientversion=self.clientversion,
        ))
        print resp

if __name__ == '__main__':
    username = sys.argv[1]
    password = getpass.getpass('Livejournal password: ')
    ljbackup = LJBackup(username, password)

