"""Connection pool for clickhouse_driver

Heavily inspired by psycopg2/lib/pool.py, this module implements a thread-safe
connection pool. Each connection is an instance of a clickhouse_driver client.
"""
import os
import threading
from time import sleep

from clickhouse_driver import Client

class ChPoolError(Exception):
    pass

class ChPool(object):
    """a threadsafe clickhouse-driver connection pool"""

    def __init__(self, connections_min: int = 10, connections_max: int = 20,
            **kwargs):
        """initialize the connection pool"""

        self.connections_min = connections_min
        self.connections_max = connections_max
        self.closed = False
        self._pool = []
        self._used = {}

        # similar to psycopg2 pools, _rused is used for mapping instances of conn
        # to their respective keys in _used
        self._rused = {}
        self._keys = 0
        self._lock = threading.Lock()

        for i in range(self.connections_min):
            self._connect(**kwargs)

    def _connect(self, key=None, **kwargs):
        """create a new conn and assign to key"""
        conn = Client(**kwargs)
        if key is not None:
            self._used[key] = conn
            self._rused[id(conn)] = key
        else:
            self._pool.append(conn)
        return conn

    def _get_key(self):
        """return unique key"""
        self._keys += 1
        return self._keys

    def get_conn(self, key=None):
        """get a free conn and assign to key if not None"""
        self._lock.acquire()
        try:
            if self.closed:
                raise ChPoolError("pool closed")
            if key is None:
                key = self._get_key()
            if key in self._used:
                return self._used[key]
            if self._pool:
                self._used[key] = conn = self._pool.pop()
                self._rused[id(conn)] = key
                return conn
            else:
                if len(self._used) == self.connections_max:
                    raise PoolError("too many conn")
                return self._connect(key)
        finally:
            self._lock.release()

    def put_conn(self, conn=None, key=None, close=False):
        """put away a conn"""

        self._lock.acquire()
        try:
            if self.closed:
                raise ChPoolError("pool closed")
            if key is None:
                key = self._rused.get(id(conn))
                if key is None:
                    raise ChPoolError("trying to put unkeyed conn")
            if len(self._pool) < self.connections_min and not close:
                # TODO: verify connection still valid
                if conn.connection.connected:
                    self._pool.append(conn)
            else:
                conn.disconnect()

            # ensure thread doesn't put connection back once the pool is closed
            if not self.closed or key in self._used:
                del self._used[key]
                del self._rused[id(conn)]
        finally:
            self._lock.release()
    def close_all_connections(self):
        """close all open connections"""

        self._lock.acquire()
        try:
            if self.closed:
                raise ChPoolError("pool closed")
            for conn in self._pool + list(self._used.values()):
                try:
                    conn.disconnect()
                except Exception:
                    pass
            self.closed = True
        finally:
            self._lock.release()