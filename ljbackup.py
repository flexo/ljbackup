import os
import sys
import time
import json
import logging
import getpass
import hashlib
import operator
import datetime
import xmlrpclib

log = logging.getLogger(__name__)

class LJBackup(object):
    clientversion = 'Python/FlexoLJBackup/0.0.1'
    timeformat = '%Y-%m-%d %H:%M:%S'

    def __init__(self, username, password, server='http://www.livejournal.com/interface/xmlrpc', dumpdir='ljbackup'):
        self.username = username
        self.password = password
        self.lj = xmlrpclib.ServerProxy(server, allow_none=True).LJ.XMLRPC
        self.dumpdir = os.path.abspath(dumpdir)
        self.challenge = None
        self.challenge_response = None
        self.time_offset = 0

    def _auth(self):
        """Re-authenticate for the next request."""
        now = time.time()
        resp = self.lj.getchallenge()
        self.challenge = resp['challenge']
        self.challenge_expires = resp['expire_time']
        self.time_offset = resp['server_time'] - now
        self.challenge_response = hashlib.md5(
            self.challenge + hashlib.md5(self.password).hexdigest()
        ).hexdigest()

    def _request(self, **kw):
        """Generate request params by updating a standard dict with **kw"""
        self._auth()
        d = dict(
            username=self.username,
            auth_method='challenge',
            auth_challenge=self.challenge,
            auth_response=self.challenge_response,
            ver=0) # version 1 enforces unicode, but complains if the entry is screwed up.
        d.update(kw)
        return d

    def _login(self):
        """Log into Livejournal. Returns personal data."""
        resp = self.lj.login(self._request(
            clientversion=self.clientversion,
        ))
        return resp

    def _write(self, data, *path):
        """Write out Python data (as JSON) to the path given."""
        strdata = json.dumps(data)
        filepath = os.path.join(*((self.dumpdir, self.username) + path))
        log.debug('Writing to %s', filepath)
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

    def _read(self, *path, **kwargs):
        """Read in some Python data (from JSON) from the path given.
        
        kwargs may include the following:

        default -- what to return if the file doesn't exist. If not
            speficied, use None.
        """
        default = kwargs.get('default', None)
        filepath = os.path.join(*((self.dumpdir, self.username) + path))
        filedir = os.path.dirname(filepath)
        log.debug('Reading from %s', filepath)
        if not os.path.isdir(filedir):
            return default
        if not os.path.exists(filepath):
            return default
        with open(filepath, 'rb') as f:
            return json.load(f, allow_none=True)

    def __call__(self):
        """Main synchronisation routine. Write out all new or updated files."""
        self.user = self._login()
        if not os.path.exists(self.dumpdir):
            try:
                os.mkdir(self.dumpdir)
            except EnvironmentError, e:
                raise
        self._write(self.user, 'user.json')
        
        lastsync = self._read('lastsync.json', default={'lastsync': None})['lastsync']

        # Ref: http://www.livejournal.com/doc/server/ljp.csp.entry_downloading.html
        log.info("Fetching list of entries to sync")
        items = {}
        count = 0
        total = -1
        while count != total:
            if lastsync is None:
                syncitems = self.lj.syncitems(self._request())
            else:
                syncitems = self.lj.syncitems(self._request(
                    lastsync=lastsync.strftime(self.timeformat)))
            count = syncitems['count']
            total = syncitems['total']
            for item in syncitems['syncitems']:
                if not item['item'].startswith('L-'):
                    continue
                item['downloaded'] = False
                item['time'] = datetime.datetime.strptime(
                    item['time'], self.timeformat)
                if lastsync is None:
                    lastsync = item['time']
                else:
                    lastsync = max(item['time'], lastsync)
                items[item['item']] = item
            log.debug("count: %r, total: %r", count, total)

        log.info('Syncing %d item%s', len(items), len(items) != 1 and 's' or '')
        while items:
            oldest = sorted(items.values(), key=operator.itemgetter('time'))[0]
            log.debug('oldest item is %r', oldest)
            lastsync = oldest['time'] - datetime.timedelta(seconds=1)
            events = self.lj.getevents(self._request(
                selecttype='syncitems',
                lastsync=lastsync.strftime(self.timeformat),
                lineendings='unix',
            ))
            for event in events['events']:
                print "event:", repr(event)
            break # DEBUG            
            remaining = [i for i in items.values() if i['downloaded'] == 0]
        # TODO - try/finally and write out last sync item

if __name__ == '__main__':
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(message)s')
    ch.setFormatter(formatter)
    log.addHandler(ch)

    username = sys.argv[1]
    password = getpass.getpass('Livejournal password: ')
    ljbackup = LJBackup(username, password)
    log.info('Commencing Backup of user %s to %s', username, ljbackup.dumpdir)
    ljbackup()
    log.info('Done')

