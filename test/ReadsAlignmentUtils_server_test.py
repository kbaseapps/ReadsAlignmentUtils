# -*- coding: utf-8 -*-
import glob
import hashlib
import inspect
import os  # noqa: F401
import shutil
import tempfile
import time
import unittest
from configparser import ConfigParser
from datetime import datetime
from os import environ
from pprint import pprint  # noqa: F401
from zipfile import ZipFile

import requests

from ReadsAlignmentUtils.authclient import KBaseAuth as _KBaseAuth
from ReadsAlignmentUtils.ReadsAlignmentUtilsImpl import ReadsAlignmentUtils
from ReadsAlignmentUtils.ReadsAlignmentUtilsServer import MethodContext
from installed_clients.AbstractHandleClient import AbstractHandle as HandleService
from installed_clients.AssemblyUtilClient import AssemblyUtil
from installed_clients.DataFileUtilClient import DataFileUtil
from installed_clients.GenomeFileUtilClient import GenomeFileUtil
from installed_clients.ReadsUtilsClient import ReadsUtils
from installed_clients.WorkspaceClient import Workspace


def dictmerge(x, y):
    z = x.copy()
    z.update(y)
    return z


class ReadsAlignmentUtilsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.token = environ.get('KB_AUTH_TOKEN', None)
        cls.callbackURL = environ.get('SDK_CALLBACK_URL')
        config_file = environ.get('KB_DEPLOYMENT_CONFIG', None)
        cls.cfg = {}
        config = ConfigParser()
        config.read(config_file)
        for nameval in config.items('ReadsAlignmentUtils'):
            cls.cfg[nameval[0]] = nameval[1]
        # Getting username from Auth profile for token
        authServiceUrl = cls.cfg['auth-service-url']
        auth_client = _KBaseAuth(authServiceUrl)
        user_id = auth_client.get_user(cls.token)
        # WARNING: don't call any logging methods on the context object,
        # it'll result in a NoneType error
        cls.ctx = MethodContext(None)
        cls.ctx.update({'token': cls.token,
                        'user_id': user_id,
                        'provenance': [
                            {'service': 'ReadsAlignmentUtils',
                             'method': 'please_never_use_it_in_production',
                             'method_params': []
                             }],
                        'authenticated': 1})
        cls.shockURL = cls.cfg['shock-url']
        cls.wsURL = cls.cfg['workspace-url']
        cls.wsClient = Workspace(cls.wsURL)
        cls.ws = Workspace(cls.wsURL, token=cls.token)
        cls.hs = HandleService(url=cls.cfg['handle-service-url'],
                               token=cls.token)
        # create workspace
        wssuffix = int(time.time() * 1000)
        wsname = "test_alignment_" + str(wssuffix)
        cls.wsinfo = cls.wsClient.create_workspace({'workspace': wsname})
        print('created workspace ' + cls.getWsName())

        cls.serviceImpl = ReadsAlignmentUtils(cls.cfg)
        cls.readUtilsImpl = ReadsUtils(cls.callbackURL)
        cls.dfu = DataFileUtil(cls.callbackURL)
        cls.assemblyUtil = AssemblyUtil(cls.callbackURL)
        cls.gfu = GenomeFileUtil(cls.callbackURL)

        cls.scratch = cls.cfg['scratch']
        cls.callback_url = os.environ['SDK_CALLBACK_URL']

        cls.staged = {}
        cls.nodes_to_delete = []
        cls.handles_to_delete = []
        cls.setupTestData()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'wsName'):
            cls.wsClient.delete_workspace({'workspace': cls.wsName})
            print('Test workspace was deleted')
        if hasattr(cls, 'nodes_to_delete'):
            for node in cls.nodes_to_delete:
                cls.delete_shock_node(node)
        if hasattr(cls, 'handles_to_delete'):
            cls.hs.delete_handles(cls.hs.hids_to_handles(cls.handles_to_delete))
            print('Deleted handles ' + str(cls.handles_to_delete))

    def getWsClient(self):
        return self.wsClient

    @classmethod
    def getWsName(cls):
        return cls.wsinfo[1]

    @classmethod
    def getImpl(cls):
        return cls.serviceImpl

    def getContext(self):
        return self.ctx

    @classmethod
    def delete_shock_node(cls, node_id):
        header = {'Authorization': 'Oauth {0}'.format(cls.token)}
        requests.delete(cls.shockURL + '/node/' + node_id, headers=header,
                        allow_redirects=True)
        print('Deleted shock node ' + node_id)

    @classmethod
    def upload_file_to_shock(cls, file_path):
        """
        Use HTTP multi-part POST to save a file to a SHOCK instance.
        """
        header = dict()
        header["Authorization"] = "Oauth {0}".format(cls.token)

        if file_path is None:
            raise Exception("No file given for upload to SHOCK!")

        with open(os.path.abspath(file_path), 'rb') as dataFile:
            files = {'upload': dataFile}
            print('POSTing data')
            response = requests.post(
                cls.shockURL + '/node', headers=header, files=files,
                stream=True, allow_redirects=True)
            print('got response')

        if not response.ok:
            response.raise_for_status()

        result = response.json()

        if result['error']:
            raise Exception(result['error'][0])
        else:
            return result["data"]

    @classmethod
    def upload_file_to_shock_and_get_handle(cls, test_file):
        """
        Uploads the file in test_file to shock and returns the node and a
        handle to the node.
        """
        print('loading file to shock: ' + test_file)
        node = cls.upload_file_to_shock(test_file)
        pprint(node)
        cls.nodes_to_delete.append(node['id'])

        print('creating handle for shock id ' + node['id'])
        handle_id = cls.hs.persist_handle({'id': node['id'],
                                           'type': 'shock',
                                           'url': cls.shockURL
                                           })
        cls.handles_to_delete.append(handle_id)

        md5 = node['file']['checksum']['md5']
        return node['id'], handle_id, md5, node['file']['size']

    @classmethod
    def upload_reads(cls, wsobjname, object_body, fwd_reads,
                     rev_reads=None, single_end=False, sequencing_tech='Illumina',
                     single_genome='1'):

        ob = dict(object_body)  # copy
        ob['sequencing_tech'] = sequencing_tech
        #        ob['single_genome'] = single_genome
        ob['wsname'] = cls.getWsName()
        ob['name'] = wsobjname
        if single_end or rev_reads:
            ob['interleaved'] = 0
        else:
            ob['interleaved'] = 1
        print('\n===============staging data for object ' + wsobjname +
              '================')
        print('uploading forward reads file ' + fwd_reads['file'])
        fwd_id, fwd_handle_id, fwd_md5, fwd_size = \
            cls.upload_file_to_shock_and_get_handle(fwd_reads['file'])

        ob['fwd_id'] = fwd_id
        rev_id = None
        rev_handle_id = None
        if rev_reads:
            print('uploading reverse reads file ' + rev_reads['file'])
            rev_id, rev_handle_id, rev_md5, rev_size = \
                cls.upload_file_to_shock_and_get_handle(rev_reads['file'])
            ob['rev_id'] = rev_id
        obj_ref = cls.readUtilsImpl.upload_reads(ob)
        objdata = cls.wsClient.get_object_info_new({
            'objects': [{'ref': obj_ref['obj_ref']}]
        })[0]
        cls.staged[wsobjname] = {'info': objdata,
                                 'ref': cls.make_ref(objdata),
                                 'fwd_node_id': fwd_id,
                                 'rev_node_id': rev_id,
                                 'fwd_handle_id': fwd_handle_id,
                                 'rev_handle_id': rev_handle_id
                                 }

    @classmethod
    def upload_genome(cls, wsobj_name, file_name):
        genbank_file_path = os.path.join(cls.scratch, file_name)
        shutil.copy(os.path.join('data', file_name), genbank_file_path)
        genome_obj = cls.gfu.genbank_to_genome({'file': {'path': genbank_file_path},
                                                'workspace_name': cls.getWsName(),
                                                'genome_name': wsobj_name,
                                                'source': 'Ensembl',
                                                'generate_ids_if_needed': 1,
                                                'generate_missing_genes': 1
                                                })
        cls.staged[wsobj_name] = {'info': genome_obj['genome_info'],
                                  'ref': genome_obj['genome_ref']}

    @classmethod
    def upload_assembly(cls, wsobj_name, file_name):
        fasta_path = os.path.join(cls.scratch, file_name)
        shutil.copy(os.path.join('data', file_name), fasta_path)
        assembly_ref = cls.assemblyUtil.save_assembly_from_fasta({'file': {'path': fasta_path},
                                                                  'workspace_name': cls.getWsName(),
                                                                  'assembly_name': wsobj_name
                                                                  })
        cls.staged[wsobj_name] = {'info': None,
                                  'ref': assembly_ref}

    @classmethod
    def upload_empty_data(cls, wsobjname):
        objdata = cls.wsClient.save_objects({
            'workspace': cls.getWsName(),
            'objects': [{'type': 'Empty.AType',
                         'data': {},
                         'name': 'empty'
                         }]
        })[0]
        cls.staged[wsobjname] = {'info': objdata,
                                 'ref': cls.make_ref(objdata),
                                 }

    @classmethod
    def save_ws_obj(cls, obj, objname, objtype):
        return cls.ws.save_objects({
            'workspace': cls.getWsName(),
            'objects': [{'type': objtype,
                         'data': obj,
                         'name': objname
                         }]
        })[0]

    @classmethod
    def setupTestFile(cls, file_name):

        file_base, file_ext = os.path.splitext(file_name)

        timestamp = int((datetime.utcnow() - datetime.utcfromtimestamp(0)).total_seconds() * 1000)
        upload_dir = os.path.join(cls.scratch, 'upload_' + file_ext[1:] + '_' + str(timestamp))
        os.mkdir(upload_dir)

        ret = {}
        ret['name'] = file_name
        ret['data_file'] = os.path.join('data/', file_name)
        ret['file_path'] = os.path.join(upload_dir, file_name)
        ret['size'] = cls.getSize(ret.get('data_file'))
        ret['md5'] = cls.md5(ret.get('data_file'))

        return ret

    @classmethod
    def setupTestData(cls):

        cls.test_bam_file = cls.setupTestFile('accepted_hits.bam')
        cls.test_bai_file = cls.setupTestFile('accepted_hits.bai')
        cls.test_sam_file = cls.setupTestFile('accepted_hits.sam')

        shutil.copy(cls.test_bam_file['data_file'], cls.test_bam_file['file_path'])
        shutil.copy(cls.test_sam_file['data_file'], cls.test_sam_file['file_path'])

        int_reads = {'file': 'data/interleaved.fq',
                     'name': '',
                     'type': ''}
        cls.upload_reads('intbasic', {'single_genome': 1}, int_reads)
        cls.upload_genome('test_genome', 'minimal.gbff')
        cls.upload_assembly('test_assembly', 'test.fna')
        cls.upload_empty_data('empty')

        cls.more_upload_params = {
                                  'read_library_ref': cls.getWsName() + '/intbasic',
                                  'assembly_or_genome_ref': cls.getWsName() + '/test_assembly',
                                  'condition': 'test_condition'
                                 }
        params = dictmerge({'destination_ref': cls.getWsName() + '/test_bam',
                            'file_path': cls.test_bam_file['file_path'],
                            'validate': 'True'
                            }, cls.more_upload_params)
        cls.getImpl().upload_alignment(cls.ctx, params)

        params = dictmerge({'destination_ref': cls.getWsName() + '/test_sam',
                            'file_path': cls.test_sam_file['file_path'],
                            'validate': 'True'
                            }, cls.more_upload_params)
        cls.getImpl().upload_alignment(cls.ctx, params)

    @classmethod
    def make_ref(cls, objinfo):
        return str(objinfo[6]) + '/' + str(objinfo[0]) + '/' + str(objinfo[4])

    @classmethod
    def getSize(cls, filename):
        return os.path.getsize(filename)

    @classmethod
    def md5(cls, filename):
        with open(filename, 'rb') as file_:
            hash_md5 = hashlib.md5()
            buf = file_.read(65536)
            while len(buf) > 0:
                hash_md5.update(buf)
                buf = file_.read(65536)
            return hash_md5.hexdigest()

    # NOTE: According to Python unittest naming rules test method names should start from 'test'. # noqa

    def upload_alignment_success(self, params, expected):

        obj = self.dfu.get_objects(
            {'object_refs': [params.get('destination_ref')]})['data'][0]

        print("============ GET OBJECTS OUTPUT ==============")
        pprint(obj)
        print("==============================================")

        self.assertEqual(obj['info'][2].startswith(
            'KBaseRNASeq.RNASeqAlignment'), True)
        d = obj['data']
        self.assertEqual(d['genome_id'], params.get('assembly_or_genome_ref'))
        self.assertEqual(d['condition'], params.get('condition'))
        self.assertEqual(d['read_sample_id'], params.get('read_library_ref'))
        self.assertEqual(d['library_type'].startswith('KBaseFile.PairedEndLibrary'), True)

        self.assertEqual(d['size'], expected.get('size'))

        f = d['file']
        self.assertEqual(f['file_name'], expected.get('name'))
        self.assertEqual(f['remote_md5'], expected.get('md5'))

        node = f['id']
        self.nodes_to_delete.append(node)

    def check_file(self, file_path, expected):

        out_dir, file_name = os.path.split(file_path)
        size = os.path.getsize(file_path)
        md5 = self.md5(file_path)

        self.assertEqual(size, expected['size'])
        self.assertEqual(md5, expected['md5'])

    def download_alignment_success(self, obj_name, expectedBAM, expectedSAM, expectedBAI):

        test_name = inspect.stack()[1][3]
        print('\n**** starting expected download success test: ' + test_name + ' ***\n')

        params = {'source_ref': self.getWsName() + '/' + obj_name,
                  'downloadSAM': 'True',
                  'downloadBAI': 'True'}

        ret = self.getImpl().download_alignment(self.ctx, params)[0]
        print("=================  DOWNLOADED FILES =================== ")
        pprint(ret)
        print("========================================================")

        bam_file_path = os.path.join(ret.get('destination_dir'), self.test_bam_file.get('name'))
        sam_file_path = glob.glob(ret.get('destination_dir') + '/*.sam')[0]
        bai_file_path = glob.glob(ret.get('destination_dir') + '/*.bai')[0]

        self.check_file(bam_file_path, expectedBAM)
        self.check_file(sam_file_path, expectedSAM)
        self.check_file(bai_file_path, expectedBAI)

    def test_upload_success_bam(self):

        params = dictmerge({'destination_ref': self.getWsName() + '/test_bam',
                            'file_path': self.test_bam_file['file_path'],
                            'validate': 'True'
                            }, self.more_upload_params)
        expected = self.test_bam_file
        self.upload_alignment_success(params, expected)

    def test_upload_success_sam(self):

        params = dictmerge({'destination_ref': self.getWsName() + '/test_sam',
                            'file_path': self.test_sam_file['file_path'],
                            'validate': 'True'
                            }, self.more_upload_params)
        expected = self.test_bam_file
        self.upload_alignment_success(params, expected)

    def test_download_success_bam(self):

        self.download_alignment_success('test_bam',
                                        self.test_bam_file,
                                        self.test_sam_file,
                                        self.test_bai_file)

    def test_download_success_sam(self):

        self.download_alignment_success('test_sam',
                                        self.test_bam_file,
                                        self.test_sam_file,
                                        self.test_bai_file)

    def test_get_aligner_stats(self):

        # test_bam_file = os.path.join("data", "accepted_hits.bam")
        # bam_file = os.path.join(self.scratch, os.path.basename(test_bam_file))
        # shutil.copy(test_bam_file, bam_file)

        stats_data = self.getImpl()._get_aligner_stats(self.test_bam_file['file_path'])

        self.assertEqual(stats_data.get('total_reads'), 15254)
        self.assertEqual(stats_data.get('mapped_reads'), 14969)
        self.assertEqual(stats_data.get('unmapped_reads'), 285)
        self.assertEqual(stats_data.get('singletons'), 0)
        self.assertEqual(stats_data.get('multiple_alignments'), 3519)

    # Following test uses object refs from a narrative to test backward compatibility to download
    # already created Alignment objects in RNASeq. comment the next line to run the test
    @unittest.skip("skipped test_download_legacy_alignment_success")
    def test_download_legacy_alignment_success(self):

        ci_alignment_ref = '22254/23/1'
        appdev_alignment_ref = '4389/54/1'

        test_name = inspect.stack()[1][3]
        print('\n**** starting expected download success test: ' + test_name + ' ***\n')

        params = {'source_ref': appdev_alignment_ref,
                  'downloadSAM': 'True'}

        ret = self.getImpl().download_alignment(self.ctx, params)[0]
        print("=================  DOWNLOADED FILES =================== ")
        pprint(ret)
        print("=======================================================")

    def export_alignment_success(self, objname, export_params, expected_num_files,
                                 expectedBAM, expectedSAM, expectedBAI):

        test_name = inspect.stack()[1][3]
        print('\n*** starting expected export pass test: ' + test_name + ' **')
        export_params['source_ref'] = self.getWsName() + '/' + objname
        shocknode = self.getImpl().export_alignment(self.ctx, export_params)[0]['shock_id']
        node_url = self.shockURL + '/node/' + shocknode
        headers = {'Authorization': 'OAuth ' + self.token}
        r = requests.get(node_url, headers=headers, allow_redirects=True)
        fn = r.json()['data']['file']['name']
        tempdir = tempfile.mkdtemp(dir=self.scratch)
        file_path = os.path.join(tempdir, test_name) + '.zip'
        print('zip file path: ' + file_path)
        print('downloading shocknode ' + shocknode)
        with open(file_path, 'wb') as fhandle:
            r = requests.get(node_url + '?download_raw', stream=True,
                             headers=headers, allow_redirects=True)
            for chunk in r.iter_content(1024):
                if not chunk:
                    break
                fhandle.write(chunk)
        with ZipFile(file_path) as z:
            z.extractall(tempdir)
        print('zip file contents: ' + str(os.listdir(tempdir)))
        count = 0

        for f in os.listdir(tempdir):
            if '.bam' in f:
                print('BAM file: ' + f)
                count += 1
                md5 = self.md5(os.path.join(tempdir, f))
                self.assertEqual(md5, expectedBAM.get('md5'))
            if '.sam' in f:
                print('SAM file: ' + f)
                count += 1
                md5 = self.md5(os.path.join(tempdir, f))
                self.assertEqual(md5, expectedSAM.get('md5'))
            if '.bai' in f:
                count += 1
                print('BAI file: ' + f)
                md5 = self.md5(os.path.join(tempdir, f))
                self.assertEqual(md5, expectedBAI.get('md5'))
        self.assertEqual(count, expected_num_files)

    def test_success_export_alignment_bam(self):

        opt_params = {'exportSAM': 'True',
                      'exportBAI': 'True'}

        self.export_alignment_success('test_bam', opt_params, 3,
                                      self.test_bam_file,
                                      self.test_sam_file,
                                      self.test_bai_file)

    def test_success_export_alignment_sam(self):

        opt_params = {'exportSAM': 'True',
                      'exportBAI': 'True'}

        self.export_alignment_success('test_sam', opt_params, 3,
                                      self.test_bam_file,
                                      self.test_sam_file,
                                      self.test_bai_file)

    def test_valid_validate_alignment(self):
        params = {'file_path': '/kb/module/test/data/samtools/accepted_hits.sam',
                  'ignore': ['MATE_NOT_FOUND', 'MISSING_READ_GROUP',
                             'INVALID_MAPPING_QUALITY']}

        ret = self.getImpl().validate_alignment(self.ctx, params)[0]

        self.assertEqual(True, ret['validated'])

        params = {'file_path': '/kb/module/test/data/samtools/accepted_hits.sam'}

        ret = self.getImpl().validate_alignment(self.ctx, params)[0]

        self.assertEqual(True, ret['validated'])

    def test_valid_invalidate_alignment(self):
        params = {'file_path': '/kb/module/test/data/samtools/accepted_hits_invalid.sam',
                  'ignore': ['MATE_NOT_FOUND', 'MISSING_READ_GROUP',
                             'INVALID_MAPPING_QUALITY']}

        ret = self.getImpl().validate_alignment(self.ctx, params)[0]

        self.assertEqual(False, ret['validated'])

    def fail_upload_alignment(self, params, error, exception=ValueError, do_startswith=False):

        test_name = inspect.stack()[1][3]
        print('\n*** starting expected upload fail test: ' + test_name + ' **')

        with self.assertRaises(exception) as context:
            self.getImpl().upload_alignment(self.ctx, params)
        if do_startswith:
            self.assertTrue(str(context.exception).startswith(error),
                            "Error message {} does not start with {}".format(
                                str(context.exception),
                                error))
        else:
            self.assertEqual(error, str(context.exception))

    def test_upload_fail_empty_reads(self):

        params = dictmerge({
                'destination_ref': self.getWsName() + '/test_download_sam',
                'file_path': self.test_sam_file['file_path']
            }, self.more_upload_params)

        params['read_library_ref'] = self.getWsName() + '/empty'

        self.fail_upload_alignment(params, 'read_library_ref parameter should be of type ' +
                                   'KBaseFile.SingleEndLibrary or KBaseFile.PairedEndLibrary or ' +
                                   'KBaseAssembly.SingleEndLibrary or KBaseAssembly.PairedEndLibrary')

    def test_upload_fail_no_dst_ref(self):
        self.fail_upload_alignment(
            dictmerge({
                        'condition': 'bar',
                        'file_path': 'test'
                       }, self.more_upload_params),
            'destination_ref parameter is required')

    def test_upload_fail_no_ws_name(self):
        self.fail_upload_alignment(
            dictmerge({
                         'condition': 'bar',
                         'destination_ref': '/foo',
                         'file_path': 'test'
                       }, self.more_upload_params),
            'Workspace name or id is required in destination_ref')

    def test_upload_fail_no_obj_name(self):
        self.fail_upload_alignment(
            dictmerge({
                         'condition': 'bar',
                         'destination_ref': self.getWsName() + '/',
                         'file_path': 'test'
                       }, self.more_upload_params),
            'Object name or id is required in destination_ref')

    def test_upload_fail_no_file(self):
        self.fail_upload_alignment(
            dictmerge({
                         'destination_ref': self.getWsName()+'/foo'
                       }, self.more_upload_params),
            'file_path parameter is required')

    def test_upload_fail_non_existant_file(self):
        self.fail_upload_alignment(
            dictmerge({
                'destination_ref': self.getWsName()+'/foo',
                'file_path': 'foo'
            }, self.more_upload_params),
            'File does not exist: foo')


    def test_upload_fail_bad_wsname(self):
        self.fail_upload_alignment(
            dictmerge({
                        'destination_ref': '&bad' + '/foo',
                        'file_path': 'foo'
                          }, self.more_upload_params),
            "'Illegal character in workspace name &bad: &'")

    def test_upload_fail_non_existant_wsname(self):
        self.fail_upload_alignment(
            dictmerge({
                        'destination_ref': '1s' + '/foo',
                        'file_path': 'bar'
                      }, self.more_upload_params),
            "'No workspace with name 1s exists'")


