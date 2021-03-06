#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# vim: set et sw=4 ts=4 sts=4 ff=unix fenc=utf8:
# Author: Binux<17175297.hk@gmail.com>
#         http://binux.me
# Created on 2012-11-15 17:27:54

import time
import umsgpack
import Queue as BaseQueue
import socket
import select
import threading
import pika
import pika.exceptions


def catch_error(func):
    def wrap(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (
                select.error,
                socket.error,
                pika.exceptions.ConnectionClosed,
                pika.exceptions.AMQPConnectionError
        ):
            self.reconnect()
            return func(self, *args, **kwargs)
    return wrap


class Queue(object):
    Empty = BaseQueue.Empty
    Full = BaseQueue.Full
    max_timeout = 0.3

    def __init__(self, name, amqp_url='amqp://guest:guest@localhost:5672/%2F',
                 maxsize=0, lazy_limit=True):
        self.name = name
        self.amqp_url = amqp_url
        self.maxsize = maxsize
        self.lock = threading.Lock()

        self.lazy_limit = lazy_limit
        if self.lazy_limit and self.maxsize:
            self.qsize_diff_limit = int(self.maxsize * 0.1)
        else:
            self.qsize_diff_limit = 0
        self.qsize_diff = 0

        self.reconnect()

    def reconnect(self):
        self.connection = pika.BlockingConnection(pika.URLParameters(self.amqp_url))
        self.channel = self.connection.channel()
        self.channel.queue_declare(self.name)
        #self.channel.queue_purge(self.name)

    @catch_error
    def qsize(self):
        with self.lock:
            ret = self.channel.queue_declare(self.name, passive=True)
        return ret.method.message_count

    def empty(self):
        if self.qsize() == 0:
            return True
        else:
            return False

    def full(self):
        if self.maxsize and self.qsize() >= self.maxsize:
            return True
        else:
            return False

    @catch_error
    def put(self, obj, block=True, timeout=None):
        if not block:
            return self.put_nowait()

        start_time = time.time()
        while True:
            try:
                return self.put_nowait(obj)
            except BaseQueue.Full:
                if timeout:
                    lasted = time.time() - start_time
                    if timeout > lasted:
                        time.sleep(min(self.max_timeout, timeout - lasted))
                    else:
                        raise
                else:
                    time.sleep(self.max_timeout)

    @catch_error
    def put_nowait(self, obj):
        if self.lazy_limit and self.qsize_diff < self.qsize_diff_limit:
            pass
        elif self.full():
            raise BaseQueue.Full
        else:
            self.qsize_diff = 0
        with self.lock:
            self.qsize_diff += 1
            return self.channel.basic_publish("", self.name, umsgpack.packb(obj))

    @catch_error
    def get(self, block=True, timeout=None, ack=False):
        if not block:
            return self.get_nowait()

        start_time = time.time()
        while True:
            try:
                return self.get_nowait(ack)
            except BaseQueue.Empty:
                if timeout:
                    lasted = time.time() - start_time
                    if timeout > lasted:
                        time.sleep(min(self.max_timeout, timeout - lasted))
                    else:
                        raise
                else:
                    time.sleep(self.max_timeout)

    @catch_error
    def get_nowait(self, ack=False):
        with self.lock:
            method_frame, header_frame, body = self.channel.basic_get(self.name, not ack)
            if method_frame is None:
                raise BaseQueue.Empty
            if ack:
                self.channel.basic_ack(method_frame.delivery_tag)
        return umsgpack.unpackb(body)

    @catch_error
    def delete(self):
        with self.lock:
            return self.channel.queue_delete(queue=self.name)
