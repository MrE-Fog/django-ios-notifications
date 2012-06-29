# -*- coding: utf-8 -*-
import socket
import ssl
import struct
from binascii import unhexlify

from django.db import models
from django.utils import simplejson as json


class NotificationPayloadSizeExceeded(Exception):
    message = 'The notification maximum payload size of 256 bytes was exceeded'


class NotConnectedException(Exception):
    message = 'You must open a socket connection before writing a message'


class APNService(models.Model):
    """
    Represents an Apple Notification Service either for live
    or sandbox notifications.

    `private_key` is optional if both the certificate and key are provided in
    `certificate`.
    """
    name = models.CharField(max_length=255)
    hostname = models.CharField(max_length=255)
    certificate = models.TextField()
    private_key = models.TextField(null=True, blank=True)

    PORT = 2195
    ssl_socket = None
    fmt = '!BH32sH%ds'

    def push_notification_to_all_devices(self, notification):
        if self.connect():
            self.write_message(notification, self.device_set.filter(is_active=True))
            self.disconnect()

    def connect(self):
        # TODO: ssl in Python 2.x does not support certficates as a string
        # See http://bugs.python.org/issue3823
        # May need to look into pyOpenSSL or M2Crypto to handle ssl connection
        # both of which expose certificate and key objects
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        certificate = self.certificate
        if self.private_key is not None:
            certificate += self.private_key
        try:
            self.ssl_socket = ssl.wrap_socket(sock, certfile=certificate, ssl_version=ssl.PROTOCOL_SSLv3)
            self.ssl_socket.connect((self.hostname, self.PORT))
            return True
        except ssl.SSLError as e:
            print e
            return False

    def write_message(self, notification, devices):
        if not isinstance(notification, Notification):
            raise TypeError('notification should be an instance of notify_ios.models.Notification')
        if self.ssl_socket is None:
            raise NotConnectedException

        aps = {'alert': notification.message}
        if notification.badge is not None:
            aps['badge'] = notification.bage
        if notification.sound is not None:
            aps['sound'] = notification.sound

        message = {'aps': {'aps': aps}}
        payload = json.dumps(message, separators=(',', ':'))

        if len(payload) > 256:
            raise NotificationPayloadSizeExceeded

        for device in devices:
            self.ssl_socket.write(self.pack_message(payload, device))

    def pack_message(self, payload, device):
        if len(payload) > 256:
            raise NotificationPayloadSizeExceeded
        if not isinstance(device, Device):
            raise TypeError('device must be an instance of notify_ios.models.Device')

        _format = self.fmt % len(payload)
        msg = struct.pack(_format, chr(0), 32, unhexlify(device.token), len(payload), payload)
        return msg

    def disconnect(self):
        if self.ssl_socket is not None:
            self.ssl_socket.close()

    def __unicode__(self):
        return u'APNService %s' % self.name


class Notification(models.Model):
    service = models.ForeignKey(APNService)
    message = models.CharField(max_length=200)
    badge = models.PositiveIntegerField(default=1, null=True)
    sound = models.CharField(max_length=30, null=True, default='default')
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    def push__all_devices(self):
        for device in Device.objects.filter(is_active=True):
            device.push_notification(self)

    def __unicode__(self):
        return u'Notification: %s' % self.message


class Device(models.Model):
    """
    Represents an iOS device with unique token.
    """
    token = models.CharField(max_length=64, blank=False, null=False)
    is_active = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    def push_notification(self, notification):
        """
        Pushes a notify_ios.models.Notification instance to an the device.
        For more details see http://developer.apple.com/library/mac/#documentation/NetworkingInternet/Conceptual/RemoteNotificationsPG/ApplePushService/ApplePushService.html
        """
        if not isinstance(notification, Notification):
            raise TypeError('notification should be an instance of notify_ios.models.Notification')

        if notification.service.connect():
            notification.service.write_message(notification, (self,))
            notification.service.disconnect()

    def __unicode__(self):
        return u'Device %s' % self.token