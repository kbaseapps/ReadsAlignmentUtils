# -*- coding: utf-8 -*-
import unittest
import logging
import sys
import os  # noqa: F401
import time
import hashlib

from os import environ
try:
    from ConfigParser import ConfigParser  # py2
except ImportError:
    from configparser import ConfigParser  # py3

from installed_clients.WorkspaceClient import Workspace as workspaceService
from ReadsAlignmentUtils.ReadsAlignmentUtilsImpl import ReadsAlignmentUtils
from ReadsAlignmentUtils.ReadsAlignmentUtilsServer import MethodContext
from ReadsAlignmentUtils.authclient import KBaseAuth as _KBaseAuth
from ReadsAlignmentUtils.core.sam_tools import SamTools


class SamToolsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.__LOGGER = logging.getLogger('SamTools_test')
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

    def test_valid_convert_sam_to_bam(self):
        opath = '/kb/module/work/'
        ofile = 'accepted_hits_valid_test_output.bam'

        if os.path.exists(opath + ofile):
            os.remove(opath + ofile)

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        result = samt.convert_sam_to_sorted_bam(ifile='accepted_hits.sam',
                                                ipath='/kb/module/test/data/samtools',
                                                ofile=ofile,
                                                opath=opath)

        self.assertEquals(result, 0)
        self.assertTrue(os.path.exists(opath + ofile))
        self.assertEquals(hashlib.md5(open(opath + ofile, 'rb').read()).hexdigest(),
                          '96c59589b0ed7338ff27de1881cf40b3')

    def test_invalid_convert_sam_to_bam(self):
        opath = '/kb/module/work/'
        ofile = 'accepted_hits_valid_test_output.bam'

        if os.path.exists(opath + ofile):
            os.remove(opath + ofile)

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        result = samt.convert_sam_to_sorted_bam(ifile='accepted_hits_invalid.sam',
                                                ipath='/kb/module/test/data/samtools',
                                                ofile=ofile,
                                                opath=opath, validate=True)

        self.assertEquals(result, 1)

    def test_valid_convert_bam_to_sam(self):
        opath = '/kb/module/work/'
        ofile = 'accepted_hits_valid_test_output.sam'

        if os.path.exists(opath + ofile):
            os.remove(opath + ofile)

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        result = samt.convert_bam_to_sam(ifile='accepted_hits_sorted.bam',
                                         ipath='/kb/module/test/data/samtools',
                                         ofile=ofile,
                                         opath=opath)

        self.assertEquals(result, 0)
        self.assertTrue(os.path.exists(opath + ofile))
        self.assertEquals(hashlib.md5(open(opath + ofile, 'rb').read()).hexdigest(),
                          'e8fd0e3d115bef90a520c831a0fbf478')

    def test_invalid_convert_bam_to_sam(self):
        opath = '/kb/module/work/'
        ofile = 'accepted_hits_invalid.sam'

        if os.path.exists(opath + ofile):
            os.remove(opath + ofile)

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        result = samt.convert_bam_to_sam(ifile='accepted_hits_invalid.bam',
                                         ipath='/kb/module/test/data/samtools',
                                         ofile=ofile,
                                         opath=opath, validate=True)

        self.assertEquals(result, 1)

    def test_valid_create_bai_from_bam(self):
        opath = '/kb/module/work/'
        ofile = 'accepted_hits_valid_test_output.bai'

        if os.path.exists(opath + ofile):
            os.remove(opath + ofile)

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        result = samt.create_bai_from_bam(ifile='accepted_hits_sorted.bam',
                                          ipath='/kb/module/test/data/samtools',
                                          ofile=ofile,
                                          opath=opath)

        self.assertEquals(result, 0)
        self.assertTrue(os.path.exists(opath + ofile))
        self.assertEquals(hashlib.md5(open(opath + ofile, 'rb').read()).hexdigest(),
                          '479a05f10c62e47c68501b7551d44593')

    def test_invalid_create_bai_from_bam(self):
        opath = '/kb/module/work/'
        ofile = 'accepted_hits_valid_test_output.bai'

        if os.path.exists(opath + ofile):
            os.remove(opath + ofile)

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        result = samt.create_bai_from_bam(ifile='accepted_hits_invalid.bam',
                                          ipath='/kb/module/test/data/samtools',
                                          ofile=ofile,
                                          opath=opath, validate=True)

        self.assertEquals(result, 1)

    def test_get_stats(self):

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        stats = samt.get_stats(ifile='accepted_hits.sam',
                               ipath='/kb/module/test/data/samtools')

        self.assertEquals(stats['unmapped_reads'], 285)
        self.assertEquals(stats['mapped_reads'], 19213)
        self.assertEquals(stats['singletons'], 0)
        self.assertEquals(stats['total_reads'], 19498)

    def test__is_valid(self):
        result = '\n' + \
                 ' \n' + \
                 '## HISTOGRAM	java.lang.String\n' + \
                 'Error Type	Count\n' + \
                 'ERROR:MISSING_READ_GROUP	1\n' + \
                 'WARNING:RECORD_MISSING_READ_GROUP	19498\n'
        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        self.assertFalse(samt._is_valid(result, None))
        self.assertTrue(samt._is_valid(result, ['MISSING_READ_GROUP']))

    def test_valid_validate(self):

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        rval = samt.validate(ifile='accepted_hits.sam',
                             ipath='/kb/module/test/data/samtools',
                             ignore=['MISSING_READ_GROUP'])

        self.assertEquals(0, rval)

    def test_invalid_validate(self):

        samt = SamTools(self.__class__.cfg, self.__class__.__LOGGER)

        rval = samt.validate(ifile='accepted_hits_invalid.sam',
                             ipath='/kb/module/test/data/samtools')

        self.assertEquals(1, rval)

if __name__ == '__main__':
      unittest.main()

