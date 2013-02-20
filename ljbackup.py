import os
import sys
import time
import json
import base64
import logging
import getpass
import hashlib
import operator
import datetime
import traceback
import xmlrpclib

log = logging.getLogger(__name__)

def json_serialise(obj):
    """Function for json.dump to allow it to serialise non-obvious types."""
    if isinstance(obj, datetime.datetime):
        return {
            '__type__': 'datetime.datetime',
            'year': obj.year,
            'month': obj.month,
            'day': obj.day,
            'hour': obj.hour,
            'minute': obj.minute,
            'second': obj.second,
            'microsecond': obj.microsecond}
    elif isinstance(obj, xmlrpclib.Binary):
        return {
            '__type__': 'xmlrpclib.Binary',
            'data': base64.b64encode(obj.data)}
    raise TypeError("Can't serialise %r (type %s)" % (obj, type(obj)))

def json_unserialise(d):
    type_ = d.get('__type__')
    if type_ == 'datetime.datetime':
        return datetime.datetime(
            year = d['year'],
            month = d['month'],
            day = d['day'],
            hour = d['hour'],
            minute = d['minute'],
            second = d['second'],
            microsecond = d['microsecond'])
    elif type_ == 'xmlrpclib.Binary':
        b = xmlrpclib.Binary()
        b.data = base64.b64decode(d['data'])
        return b
    return d

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
        strdata = json.dumps(data, default=json_serialise)
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
            return json.load(f, object_hook=json_unserialise)

    def __call__(self):
        """Main synchronisation routine. Write out all new or updated files."""
        self.user = self._login()
        if not os.path.exists(self.dumpdir):
            try:
                os.mkdir(self.dumpdir)
            except EnvironmentError, e:
                raise
        self._write(self.user, 'user.json')
        
        lastsync = self._read('lastsync.json', default={}).get('lastsync', None)

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
                items[int(item['item'].replace('L-', ''))] = item
            log.debug("count: %r, total: %r", count, total)

        log.info('Syncing %d item%s', len(items), len(items) != 1 and 's' or '')
        try:
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
                    self._process_entry(event)
                    items[event['itemid']]['downloaded'] = True
                # keep only undownloaded items:
                items = [i for i in items.values() if i['downloaded'] == 0]
        except KeyboardInterrupt:
            log.info('Received ^C; quitting.')
        except:
            log.error('Something\'s gone wrong. Please file a bug.')
            print >> sys.stderr, traceback.format_exc()
            raise
        finally:
            # write out last sync item
            log.debug('Writing out final sync time %s', lastsync)
            self._write({'lastsync': lastsync}, 'lastsync.json')

    def _process_entry(self, entry):
        """Process a single entry returned as part of a syncitems call."""
        # entry looks something along the lines of:
        # {'itemid': 3, 'eventtime': '2003-03-23 14:55:00', 'url': 'http://user.livejournal.com/825392.html', 'ditemid': 920, 'event_timestamp': 1048431300, 'reply_count': 1, 'logtime': '2003-03-23 06:55:33', 'props': {'current_moodid': 3, 'personifi_tags': 'nterms:no', 'commentalter': 1055945724}, 'can_comment': 1, 'anum': 152, 'event': "[main journal text, exactly as entered (eg newlines rather than <br />s", 'subject': '[subject line]'}
        # eventtime is "The time the user posted (or said they posted, rather,
        # since users can back-date posts)".
        # logtime isn't documented but judging from the fact the post I
        # copied above was UTC, it's LJ's server time (UTC-0500 - USA Eastern,
        # it seems)
        date = datetime.datetime.strptime(entry['eventtime'], self.timeformat)
        path = [
            "%04d" % date.year,
            "%02d" % date.month,
            date.strftime('%Y-%m-%d-%H-%M-%S.json')]
        self._write(entry, *path)
        # TODO - comments

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

