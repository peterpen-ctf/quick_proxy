#!/usr/bin/env python

import os
import socket
import errno
import re
from datetime import datetime
from time import sleep
from threading import Thread
from glob import glob
from select import select
from imp import reload

import config


class SocketPairs:
    def __init__(self):
        self.pairs = {}

    def add_pair(self, s1, s2):
        self.pairs[s1] = s2
        self.pairs[s2] = s1

    def get_pair(self, s):
        return self.pairs[s]

    def del_pair(self, s1, s2=None):
        if s2 is None:
            s2 = self.pairs[s1]

        del self.pairs[s1]
        del self.pairs[s2]


class Dumper:
    def __init__(self, port):
        self.rel_port_dir = "port_%d" % port
        port_dir = os.path.join(config.SESSIONS_DIR, self.rel_port_dir)
        if not os.path.exists(port_dir):
            os.makedirs(port_dir)

        filename_pattern = os.path.join(port_dir, "port%d_*.txt" % port)
        last_session_num = len(glob(filename_pattern))
        self.filename = os.path.join(port_dir, "port%d_%09d.txt" % (port, last_session_num + 1))

        self.filtered_filename = os.path.join(config.SESSIONS_DIR, "filtered_%d.html" % port)
        self.was_filtered = False

    def dump(self, data):
        with open(self.filename, "ab") as f:
            f.write(data)

    def set_was_filtered(self):
        if not self.was_filtered:
            self.was_filtered = True
            with open(self.filtered_filename, "ab") as f:
                session_filename = os.path.basename(self.filename)
                link = os.path.join(self.rel_port_dir, session_filename)
                dt = datetime.now()
                f.write('<li><a href="%s">%s</a>  %s\n' % (link, session_filename,
                                                           dt.strftime('%d-%b-%Y %H:%M')))
            

class Proxy(Thread):
    def __init__(self,
                 listen_port, server_host, server_port,
                 listen_ipv6=True):

        Thread.__init__(self, name='port' + str(listen_port))

        server_addrs = socket.getaddrinfo(server_host, server_port,
                                          0, socket.SOCK_STREAM)
        server_addr = server_addrs[0]
        if len(server_addrs) > 1:
            readable_addrs = [addr[4][0] for addr in server_addrs]
            print("host %s resolved into several addrs: %s. Using first: %s" %
                  (server_host, readable_addrs, server_addr[4][0]))

        self.listen_port = listen_port

        self.server_family   = server_addr[0]
        self.server_socktype = server_addr[1]
        self.server_proto    = server_addr[2]
        self.server_sockaddr = server_addr[4][:2]

        self.listen_ipv6     = listen_ipv6

        print("Proxy for port %s ready" % self.listen_port)

    def run(self):
        if self.listen_ipv6:
            proxy = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            proxy.bind(("::", self.listen_port))
        else:
            proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            proxy.bind(("0.0.0.0", self.listen_port))

        client_sockets = set()
        server_sockets = set()
        socket_pairs = SocketPairs()
        closed_but_data_left_sockets = set()
        data_to_send = {}
        data_to_filter = {}
        socket_to_dumper = {}

        proxy.listen(10)

        while True:
            vaild_sockets = client_sockets | server_sockets
            # clean up closed socket-pairs
            for s in list(socket_pairs.pairs):
                if (s in socket_pairs.pairs and
                    s not in vaild_sockets and
                    socket_pairs.get_pair(s) in socket_pairs.pairs and
                    socket_pairs.get_pair(s) not in vaild_sockets):
                    socket_pairs.del_pair(s)

            # clean up unused datas to send
            vaild_sockets = socket_pairs.pairs

            for s in list(data_to_send):
                if s not in vaild_sockets:
                    del data_to_send[s]

            for s in list(data_to_filter):
                if s not in vaild_sockets:
                    del data_to_filter[s]

            for s in list(socket_to_dumper):
                if s not in vaild_sockets:
                    del socket_to_dumper[s]

            try:
                want_read = set([proxy]) | client_sockets | server_sockets
                have_out_data = [s for s in data_to_send if data_to_send[s]]
                want_write = set(have_out_data)

                ready_read, ready_write = select(want_read, want_write,
                                                 [], 10)[:2]
            except:
                # clean up bad want_read's and want_write's fd
                for s in want_read:
                    try:
                        select([s], [], [], 0)
                    except:
                        client_sockets.discard(s)
                        server_sockets.discard(s)
                        data_to_send[s] = b''

                for s in want_write:
                    try:
                        select([], [s], [], 0)
                    except:
                        client_sockets.discard(s)
                        server_sockets.discard(s)
                        data_to_send[s] = b''
                continue

            # handling a new connect to the proxy
            if proxy in ready_read:
                client, address = proxy.accept()
                client.setblocking(0)

                server = socket.socket(self.server_family,
                                       self.server_socktype)
                server.setblocking(0)

                try:
                    server.connect(self.server_sockaddr)
                except socket.error as E:
                    if E.errno == errno.EINPROGRESS or E.errno == 10035:
                        pass  # it is normal to have EINPROGRESS here
                    else:
                        client.close()
                        server.close()
                        continue

                socket_to_dumper[server] = Dumper(self.listen_port)

                socket_pairs.add_pair(client, server)

                data_to_send[client]   = b''
                data_to_send[server]   = b''

                data_to_filter[client] = b''
                data_to_filter[server] = b''

                client_sockets.add(client)
                server_sockets.add(server)

                print("Connect to port %s from %s" %
                      (self.listen_port, address))

            for s in ready_read:
                if s == proxy:
                    continue  # handled above
                s_pair = socket_pairs.get_pair(s)

                try:
                    data = s.recv(65536)
                except:
                    s_pair.close()
                    break

                if data:
                    if s in server_sockets:
                        socket_to_dumper[s].dump(data)

                    # check if to filter data out, filter only server socket
                    if s in server_sockets:
                        data_to_filter[s] += data

                        for pattern in config.FILTER_RE:
                            if re.search(pattern, data_to_filter[s]):
                                print("Connection dropped at pattern %s" % pattern)
                                socket_to_dumper[s].set_was_filtered()
                                s.close()
                                s_pair.close()

                        data_to_filter[s] = (
                            data_to_filter[s][-config.FILTER_WINDOW_SIZE:]
                        )

                    data_to_send[s_pair] += data
                else:  # connection was closed
                    if s in server_sockets and data_to_send[s_pair]:
                        closed_but_data_left_sockets.add(s_pair)
                        s_pair.shutdown(socket.SHUT_RD)
                    else:
                        s_pair.close()

                    s.close()
                    break

            for s in ready_write:
                if not data_to_send[s]:
                    if s in closed_but_data_left_sockets:
                        closed_but_data_left_sockets.remove(s)
                        s.close()
                    break

                try:
                    sent = s.send(data_to_send[s])
                except:
                    socket_pairs.get_pair(s).close()
                    break

                if s in server_sockets:
                    socket_to_dumper[s].dump(data_to_send[s][:sent])

                data_to_send[s] = data_to_send[s][sent:]

for listen_port, sockaddr in config.PROXYMAPS.items():
    server_host, server_port = sockaddr
    p = Proxy(listen_port, server_host, server_port)
    p.daemon = True
    p.start()

while True:
    sleep(5)
    try:
        import config
        reload(config)
    except Exception as E:
        print("Reload failed: %s" % E)
