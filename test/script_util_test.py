# -*- coding: utf-8 -*-
import logging
import os  # noqa: F401
import sys
import time
import unittest
from configparser import ConfigParser
from os import environ

from ReadsAlignmentUtils.authclient import KBaseAuth as _KBaseAuth

from ReadsAlignmentUtils.ReadsAlignmentUtilsImpl import ReadsAlignmentUtils
from ReadsAlignmentUtils.ReadsAlignmentUtilsServer import MethodContext
from ReadsAlignmentUtils.core import script_utils
from installed_clients.WorkspaceClient import Workspace as workspaceService


class ScriptUtilsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.__LOGGER = logging.getLogger('ScriptUtils_test')
        cls.__LOGGER.setLevel(logging.INFO)
        streamHandler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s - %(filename)s - %(lineno)d - %(levelname)s - %(message)s")
        formatter.converter = time.gmtime
        streamHandler.setFormatter(formatter)
        cls.__LOGGER.addHandler(streamHandler)
        cls.__LOGGER.info("Logger was set")

        token = environ.get('KB_AUTH_TOKEN', None)
        config_file = environ.get('KB_DEPLOYMENT_CONFIG', None)
        cls.cfg = {}
        config = ConfigParser()
        config.read(config_file)
        for nameval in config.items('ReadsAlignmentUtils'):
            cls.cfg[nameval[0]] = nameval[1]
        # Getting username from Auth profile for token
        authServiceUrl = cls.cfg['auth-service-url']
        auth_client = _KBaseAuth(authServiceUrl)
        user_id = auth_client.get_user(token)
        # WARNING: don't call any logging methods on the context object,
        # it'll result in a NoneType error
        cls.ctx = MethodContext(None)
        cls.ctx.update({'token': token,
                        'user_id': user_id,
                        'provenance': [
                            {'service': 'ReadsAlignmentUtils',
                             'method': 'please_never_use_it_in_production',
                             'method_params': []
                             }],
                        'authenticated': 1})
        cls.wsURL = cls.cfg['workspace-url']
        cls.wsClient = workspaceService(cls.wsURL)
        cls.serviceImpl = ReadsAlignmentUtils(cls.cfg)
        cls.scratch = cls.cfg['scratch']
        cls.callback_url = os.environ['SDK_CALLBACK_URL']

    def test_log(self):
        script_utils.log("printing test message...")
        script_utils.log("logging test message...", logging.WARNING, self.__class__.__LOGGER)

    def test_whereis(self):
        self.assertIsNone(script_utils.whereis('no_such_program'),
                          'wat! there is a commandline program called no_such_program!')
        self.assertEqual(script_utils.whereis('ls'), '/bin/ls', 'ls program not found in path!')

if __name__ == '__main__':
      unittest.main()

