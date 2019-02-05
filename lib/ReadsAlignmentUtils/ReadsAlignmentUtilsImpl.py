# -*- coding: utf-8 -*-
#BEGIN_HEADER
import errno
import glob
import logging
import os
import re
import sys
import time
import uuid
import zipfile
from collections import Counter
from pprint import pformat
from pprint import pprint

import pysam

from ReadsAlignmentUtils.core import script_utils
from ReadsAlignmentUtils.core.sam_tools import SamTools
from installed_clients.DataFileUtilClient import DataFileUtil
from installed_clients.WorkspaceClient import Workspace
from installed_clients.baseclient import ServerError as DFUError
from installed_clients.baseclient import ServerError as WorkspaceError
#END_HEADER


class ReadsAlignmentUtils:
    '''
    Module Name:
    ReadsAlignmentUtils

    Module Description:
    A KBase module: ReadsAlignmentUtils

This module is intended for use by Aligners and Assemblers to upload and download alignment files.
The alignment may be uploaded as a sam or bam file. If a sam file is given, it is converted to
the sorted bam format and saved. Upon downloading, optional parameters may be provided to get files
in sam and bai formats from the downloaded bam file. This utility also generates stats from the
stored alignment.
    '''

    ######## WARNING FOR GEVENT USERS ####### noqa
    # Since asynchronous IO can lead to methods - even the same method -
    # interrupting each other, you must be *very* careful when using global
    # state. A method could easily clobber the state set by another while
    # the latter method is running.
    ######################################### noqa
    VERSION = "0.3.6"
    GIT_URL = "https://github.com/kbaseapps/ReadsAlignmentUtils.git"
    GIT_COMMIT_HASH = "75ef2c24694c056dfca71859d6f344ccff7d4725"

    #BEGIN_CLASS_HEADER

    PARAM_IN_FILE = 'file_path'
    PARAM_IN_SRC_REF = 'source_ref'
    PARAM_IN_DST_REF = 'destination_ref'
    PARAM_IN_CONDITION = 'condition'
    PARAM_IN_READ_LIB_REF = 'read_library_ref'
    PARAM_IN_ASM_GEN_REF = 'assembly_or_genome_ref'

    PARAM_IN_ALIGNED_USING = 'aligned_using'
    PARAM_IN_ALIGNER_VER = 'aligner_version'
    PARAM_IN_ALIGNER_OPTS = 'aligner_opts'
    PARAM_IN_REPLICATE_ID = 'replicate_id'
    PARAM_IN_PLATFORM = 'platform'
    PARAM_IN_BOWTIE2_INDEX = 'bowtie2_index'
    PARAM_IN_SAMPLESET_REF = 'sampleset_ref'
    PARAM_IN_MAPPED_SAMPLE_ID = 'mapped_sample_id'

    PARAM_IN_DOWNLOAD_SAM = 'downloadSAM'
    PARAM_IN_DOWNLOAD_BAI = 'downloadBAI'
    PARAM_IN_VALIDATE = 'validate'

    INVALID_WS_OBJ_NAME_RE = re.compile('[^\\w\\|._-]')
    INVALID_WS_NAME_RE = re.compile('[^\\w:._-]')

    def _get_file_path_info(self, file_path):
        """
        Given a file path, returns the directory, file name, file base and file extension
        """
        dir, file_name = os.path.split(file_path)
        file_base, file_ext = os.path.splitext(file_name)

        return dir, file_name, file_base, file_ext

    def _mkdir_p(self, path):
        """
        _mkdir_p: make directory for given path
        """
        if not path:
            return
        try:
            os.makedirs(path)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                raise

    def _check_required_param(self, in_params, param_list):
        """
        Checks if each of the params in the list are in the input params
        """
        for param in param_list:
            if (param not in in_params or not in_params[param]):
                raise ValueError('{} parameter is required'.format(param))

    def _proc_ws_obj_params(self, ctx, params):
        """
        Checks the validity of workspace and object params and returns them
        """
        dst_ref = params.get(self.PARAM_IN_DST_REF)

        ws_name_id, obj_name_id = os.path.split(dst_ref)

        if not bool(ws_name_id.strip()) or ws_name_id == '/':
            raise ValueError("Workspace name or id is required in " + self.PARAM_IN_DST_REF)

        if not bool(obj_name_id.strip()):
            raise ValueError("Object name or id is required in " + self.PARAM_IN_DST_REF)

        if not isinstance(ws_name_id, int):

            try:
                ws_name_id = self.dfu.ws_name_to_id(ws_name_id)
            except DFUError as se:
                prefix = se.message.split('.')[0]
                raise ValueError(prefix)

        self.__LOGGER.info('Obtained workspace name/id ' + str(ws_name_id))

        return ws_name_id, obj_name_id

    def _get_ws_info(self, obj_ref):

        ws = Workspace(self.ws_url)
        try:
            info = ws.get_object_info_new({'objects': [{'ref': obj_ref}]})[0]
        except WorkspaceError as wse:
            self.__LOGGER.error('Logging workspace exception')
            self.__LOGGER.error(str(wse))
            raise
        return info

    def _proc_upload_alignment_params(self, ctx, params):
        """
        Checks the presence and validity of upload alignment params
        """
        self._check_required_param(params, [self.PARAM_IN_DST_REF,
                                            self.PARAM_IN_FILE,
                                            self.PARAM_IN_CONDITION,
                                            self.PARAM_IN_READ_LIB_REF,
                                            self.PARAM_IN_ASM_GEN_REF
                                            ])

        ws_name_id, obj_name_id = self._proc_ws_obj_params(ctx, params)

        file_path = params.get(self.PARAM_IN_FILE)

        if not (os.path.isfile(file_path)):
            raise ValueError('File does not exist: ' + file_path)

        lib_type = self._get_ws_info(params.get(self.PARAM_IN_READ_LIB_REF))[2]
        if lib_type.startswith('KBaseFile.SingleEndLibrary') or \
           lib_type.startswith('KBaseFile.PairedEndLibrary') or \
           lib_type.startswith('KBaseAssembly.SingleEndLibrary') or \
           lib_type.startswith('KBaseAssembly.PairedEndLibrary'):
            pass
        else:
            raise ValueError(self.PARAM_IN_READ_LIB_REF + ' parameter should be of type' +
                                                          ' KBaseFile.SingleEndLibrary or' +
                                                          ' KBaseFile.PairedEndLibrary or' +
                                                          ' KBaseAssembly.SingleEndLibrary or' +
                                                          ' KBaseAssembly.PairedEndLibrary')

        obj_type = self._get_ws_info(params.get(self.PARAM_IN_ASM_GEN_REF))[2]
        if obj_type.startswith('KBaseGenomes.Genome') or \
           obj_type.startswith('KBaseGenomeAnnotations.Assembly') or \
           obj_type.startswith('KBaseGenomes.ContigSet'):
            pass
        else:
            raise ValueError(self.PARAM_IN_ASM_GEN_REF + ' parameter should be of type' +
                                                         ' KBaseGenomes.Genome or' +
                                                         ' KBaseGenomeAnnotations.Assembly or' +
                                                         ' KBaseGenomes.ContigSet')
        return ws_name_id, obj_name_id, file_path, lib_type

    def _get_aligner_stats(self, bam_file):
        """
        Gets the aligner stats from BAM file

        How we compute this stats:

        For each segment (line) in SAM/BAM file:
            we take the first element as `reads_id`
                    the second element as `flag`

            if the last bit (0x1) of flag is `1`:
                we treat this segment as paired end reads
            otherwise:
                we treat this segment as single end reads

            For single end reads:
                if the 3rd last bit (0x8) of flag is `1`:
                    we increment unmapped_reads_count
                else:
                    we treat this `reads_id` as mapped

                for all mapped `reads_ids`"
                    if it appears only once:
                        we treat this `reads_id` as `singletons`
                    else:
                        we treat this `reads_id` as `multiple_alignments`

                lastly, total_reads = unmapped_reads_count + identical mapped `reads_id`

            For paired end reads:
                if the 7th last bit (0x40) of flag is `1`:
                    if the 3rd last bit (0x8) of flag is `1`:
                        we increment unmapped_left_reads_count
                    else:
                        we treat this `reads_id` as mapped

                if the 8th last bit ( 0x80) of flag is `1`:
                    if the 3rd last bit (0x8) of flag is `1`:
                        we increment unmapped_right_reads_count
                    else:
                        we treat this `reads_id` as mapped

                for all mapped `reads_ids`"
                    if it appears only once:
                        we treat this `reads_id` as `singletons`
                    else:
                        we treat this `reads_id` as `multiple_alignments`

                lastly, total_reads = unmapped_left_reads_count + unmapped_right_reads_count + identical mapped `reads_id`
        """
        path, file = os.path.split(bam_file)

        self.__LOGGER.info('Start to generate aligner stats')
        start_time = time.time()

        infile = pysam.AlignmentFile(bam_file, 'r')

        properly_paired = 0
        unmapped_reads_count = 0
        unmapped_left_reads_count = 0
        unmapped_right_reads_count = 0
        mapped_reads_ids = []
        mapped_left_reads_ids = []
        mapped_right_reads_ids = []
        paired = False
        for alignment in infile:
            seg = alignment.to_string().split('\t')
            reads_id = seg[0]
            flag = "0000000" + "{0:b}".format(int(seg[1]))

            if flag[-1] == '1':
                paired = True

            if paired:  # process paired end sequence

                if flag[-7] == '1':  # first sequence of a pair
                    if flag[-3] == '1':
                        unmapped_left_reads_count += 1
                    else:
                        mapped_left_reads_ids.append(reads_id)

                if flag[-8] == '1':  # second sequence of a pair
                    if flag[-3] == '1':
                        unmapped_right_reads_count += 1
                    else:
                        mapped_right_reads_ids.append(reads_id)

                if flag[-2] == '1':
                    properly_paired += 1
            else:  # process single end sequence
                if flag[-3] == '1':
                    unmapped_reads_count += 1
                else:
                    mapped_reads_ids.append(reads_id)

                if flag[-2] == '1':
                    properly_paired += 1

        infile.close()

        if paired:
            mapped_reads_ids = mapped_left_reads_ids + mapped_right_reads_ids
            unmapped_reads_count = unmapped_left_reads_count + unmapped_right_reads_count

            mapped_reads_ids_counter = Counter(mapped_reads_ids)
            mapped_reads_count = len(list(mapped_reads_ids_counter))

            singletons = list(mapped_reads_ids_counter.values()).count(1)
            multiple_alignments = mapped_reads_count - singletons

            total_reads = unmapped_reads_count + mapped_reads_count

            properly_paired = properly_paired // 2

        else:
            mapped_reads_ids_counter = Counter(mapped_reads_ids)
            mapped_reads_count = len(list(mapped_reads_ids_counter))

            singletons = list(mapped_reads_ids_counter.values()).count(1)
            multiple_alignments = mapped_reads_count - singletons

            total_reads = unmapped_reads_count + mapped_reads_count

        try:
            alignment_rate = round(float(mapped_reads_count) / total_reads * 100, 3)
        except ZeroDivisionError:
            alignment_rate = 0

        if alignment_rate > 100:
                alignment_rate = 100.0

        elapsed_time = time.time() - start_time
        self.__LOGGER.info('Used: {}'.format(time.strftime("%H:%M:%S", time.gmtime(elapsed_time))))

        stats_data = {
            "alignment_rate": alignment_rate,
            "mapped_reads": mapped_reads_count,
            "multiple_alignments": multiple_alignments,
            "properly_paired": properly_paired,
            "singletons": singletons,
            "total_reads": total_reads,
            "unmapped_reads": unmapped_reads_count
        }
        return stats_data

    def _validate(self, params):
        samt = SamTools(self.config, self.__LOGGER)
        if 'ignore' in params:
            path, file = os.path.split(params['file_path'])
            rval = samt.validate(ifile=file, ipath=path,
                                 ignore=params['ignore'])
        else:
            path, file = os.path.split(params['file_path'])
            rval = samt.validate(ifile=file, ipath=path)

        return rval

    #END_CLASS_HEADER

    # config contains contents of config file in a hash or None if it couldn't
    # be found
    def __init__(self, config):
        #BEGIN_CONSTRUCTOR
        self.config = config
        self.__LOGGER = logging.getLogger('KBaseRNASeq')
        if 'log_level' in config:
            self.__LOGGER.setLevel(config['log_level'])
        else:
            self.__LOGGER.setLevel(logging.INFO)
        streamHandler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s - %(filename)s - %(lineno)d - \
                                       %(levelname)s - %(message)s")
        formatter.converter = time.gmtime
        streamHandler.setFormatter(formatter)
        self.__LOGGER.addHandler(streamHandler)
        self.__LOGGER.info("Logger was set")

        script_utils.check_sys_stat(self.__LOGGER)

        self.scratch = config['scratch']
        self.callback_url = os.environ['SDK_CALLBACK_URL']
        self.ws_url = config['workspace-url']
        self.dfu = DataFileUtil(self.callback_url)
        self.samtools = SamTools(config)
        #END_CONSTRUCTOR
        pass


    def validate_alignment(self, ctx, params):
        """
        :param params: instance of type "ValidateAlignmentParams" (* Input
           parameters for validating a reads alignment. For validation errors
           to ignore, see
           http://broadinstitute.github.io/picard/command-line-overview.html#V
           alidateSamFile) -> structure: parameter "file_path" of String,
           parameter "ignore" of list of String
        :returns: instance of type "ValidateAlignmentOutput" (* Results from
           validate alignment *) -> structure: parameter "validated" of type
           "boolean" (A boolean - 0 for false, 1 for true. @range (0, 1))
        """
        # ctx is the context object
        # return variables are: returnVal
        #BEGIN validate_alignment

        rval = self._validate(params)

        if rval == 0:
            returnVal = {'validated': True}
        else:
            returnVal = {'validated': False}

        #END validate_alignment

        # At some point might do deeper type checking...
        if not isinstance(returnVal, dict):
            raise ValueError('Method validate_alignment return value ' +
                             'returnVal is not type dict as required.')
        # return the results
        return [returnVal]

    def upload_alignment(self, ctx, params):
        """
        Validates and uploads the reads alignment
                How we compute BAM stats:
                For each segment (line) in SAM/BAM file:
                    we take the first element as `reads_id`
                            the second element as `flag`
                    if the last bit (0x1) of flag is `1`:
                        we treat this segment as paired end reads
                    otherwise:
                        we treat this segment as single end reads
                    For single end reads:
                        if the 3rd last bit (0x8) of flag is `1`:
                            we increment unmapped_reads_count
                        else:
                            we treat this `reads_id` as mapped
                        for all mapped `reads_ids`"
                            if it appears only once:
                                we treat this `reads_id` as `singletons`
                            else:
                                we treat this `reads_id` as `multiple_alignments`
                        lastly, total_reads = unmapped_reads_count + identical mapped `reads_id`
                    For paired end reads:
                        if the 7th last bit (0x40) of flag is `1`:
                            if the 3rd last bit (0x8) of flag is `1`:
                                we increment unmapped_left_reads_count
                            else:
                                we treat this `reads_id` as mapped
                        if the 8th last bit ( 0x80) of flag is `1`:
                            if the 3rd last bit (0x8) of flag is `1`:
                                we increment unmapped_right_reads_count
                            else:
                                we treat this `reads_id` as mapped
                        for all mapped `reads_ids`"
                            if it appears only once:
                                we treat this `reads_id` as `singletons`
                            else:
                                we treat this `reads_id` as `multiple_alignments`
                        lastly, total_reads = unmapped_left_reads_count + unmapped_right_reads_count + identical mapped `reads_id`
        :param params: instance of type "UploadAlignmentParams" (* Required
           input parameters for uploading a reads alignment string
           destination_ref -  object reference of alignment destination. The
           object ref is 'ws_name_or_id/obj_name_or_id' where ws_name_or_id
           is the workspace name or id and obj_name_or_id is the object name
           or id file_path              -  File with the path of the sam or
           bam file to be uploaded. If a sam file is provided, it will be
           converted to the sorted bam format before being saved
           read_library_ref       -  workspace object ref of the read sample
           used to make the alignment file condition              -
           assembly_or_genome_ref -  workspace object ref of genome assembly
           or genome object that was used to build the alignment *) ->
           structure: parameter "destination_ref" of String, parameter
           "file_path" of String, parameter "read_library_ref" of String,
           parameter "condition" of String, parameter
           "assembly_or_genome_ref" of String, parameter "aligned_using" of
           String, parameter "aligner_version" of String, parameter
           "aligner_opts" of mapping from String to String, parameter
           "replicate_id" of String, parameter "platform" of String,
           parameter "bowtie2_index" of type "ws_bowtieIndex_id", parameter
           "sampleset_ref" of type "ws_Sampleset_ref", parameter
           "mapped_sample_id" of mapping from String to mapping from String
           to String, parameter "validate" of type "boolean" (A boolean - 0
           for false, 1 for true. @range (0, 1)), parameter "ignore" of list
           of String
        :returns: instance of type "UploadAlignmentOutput" (*  Output from
           uploading a reads alignment  *) -> structure: parameter "obj_ref"
           of String
        """
        # ctx is the context object
        # return variables are: returnVal
        #BEGIN upload_alignment

        self.__LOGGER.info('Starting upload Reads Alignment, parsing parameters ')
        pprint(params)

        ws_name_id, obj_name_id, file_path, lib_type = self._proc_upload_alignment_params(ctx, params)

        dir, file_name, file_base, file_ext = self._get_file_path_info(file_path)

        if self.PARAM_IN_VALIDATE in params and params[self.PARAM_IN_VALIDATE] is True:
            if self._validate(params) == 1:
                raise Exception('{0} failed validation'.format(file_path))

        bam_file = file_path
        if file_ext.lower() == '.sam':
            bam_file = os.path.join(dir, file_base + '.bam')
            self.samtools.convert_sam_to_sorted_bam(ifile=file_name, ipath=dir, ofile=bam_file)

        uploaded_file = self.dfu.file_to_shock({'file_path': bam_file,
                                                'make_handle': 1
                                                })
        file_handle = uploaded_file['handle']
        file_size = uploaded_file['size']

        aligner_stats = self._get_aligner_stats(file_path)
        aligner_data = {'file': file_handle,
                        'size': file_size,
                        'condition': params.get(self.PARAM_IN_CONDITION),
                        'read_sample_id': params.get(self.PARAM_IN_READ_LIB_REF),
                        'library_type': lib_type,
                        'genome_id': params.get(self.PARAM_IN_ASM_GEN_REF),
                        'alignment_stats': aligner_stats
                        }
        optional_params = [self.PARAM_IN_ALIGNED_USING,
                           self.PARAM_IN_ALIGNER_VER,
                           self.PARAM_IN_ALIGNER_OPTS,
                           self.PARAM_IN_REPLICATE_ID,
                           self.PARAM_IN_PLATFORM,
                           self.PARAM_IN_BOWTIE2_INDEX,
                           self.PARAM_IN_SAMPLESET_REF,
                           self.PARAM_IN_MAPPED_SAMPLE_ID
                           ]
        for opt_param in optional_params:
            if opt_param in params and params[opt_param] is not None:
                aligner_data[opt_param] = params[opt_param]

        self.__LOGGER.info('=========  Adding extra_provenance_refs')
        self.__LOGGER.info(params.get(self.PARAM_IN_READ_LIB_REF))
        self.__LOGGER.info(params.get(self.PARAM_IN_ASM_GEN_REF))
        self.__LOGGER.info('=======================================')

        res = self.dfu.save_objects({"id": ws_name_id,
                                     "objects": [{"type": "KBaseRNASeq.RNASeqAlignment",
                                                  "data": aligner_data,
                                                  "name": obj_name_id,
                                                  "extra_provenance_input_refs":
                                                      [params.get(self.PARAM_IN_READ_LIB_REF),
                                                       params.get(self.PARAM_IN_ASM_GEN_REF)]}
                                                 ]})[0]
        self.__LOGGER.info('save complete')

        returnVal = {'obj_ref': str(res[6]) + '/' + str(res[0]) + '/' + str(res[4])}

        self.__LOGGER.info('Uploaded object: ')
        self.__LOGGER.info(returnVal)

        #END upload_alignment

        # At some point might do deeper type checking...
        if not isinstance(returnVal, dict):
            raise ValueError('Method upload_alignment return value ' +
                             'returnVal is not type dict as required.')
        # return the results
        return [returnVal]

    def download_alignment(self, ctx, params):
        """
        Downloads alignment files in .bam, .sam and .bai formats. Also downloads alignment stats *
        :param params: instance of type "DownloadAlignmentParams" (* Required
           input parameters for downloading a reads alignment string
           source_ref -  object reference of alignment source. The object ref
           is 'ws_name_or_id/obj_name_or_id' where ws_name_or_id is the
           workspace name or id and obj_name_or_id is the object name or id
           *) -> structure: parameter "source_ref" of String, parameter
           "downloadSAM" of type "boolean" (A boolean - 0 for false, 1 for
           true. @range (0, 1)), parameter "downloadBAI" of type "boolean" (A
           boolean - 0 for false, 1 for true. @range (0, 1)), parameter
           "validate" of type "boolean" (A boolean - 0 for false, 1 for true.
           @range (0, 1)), parameter "ignore" of list of String
        :returns: instance of type "DownloadAlignmentOutput" (*  The output
           of the download method.  *) -> structure: parameter
           "destination_dir" of String, parameter "stats" of type
           "AlignmentStats" -> structure: parameter "properly_paired" of
           Long, parameter "multiple_alignments" of Long, parameter
           "singletons" of Long, parameter "alignment_rate" of Double,
           parameter "unmapped_reads" of Long, parameter "mapped_reads" of
           Long, parameter "total_reads" of Long
        """
        # ctx is the context object
        # return variables are: returnVal
        #BEGIN download_alignment

        self.__LOGGER.info('Running download_alignment with params:\n' +
                 pformat(params))

        inref = params.get(self.PARAM_IN_SRC_REF)
        if not inref:
            raise ValueError('{} parameter is required'.format(self.PARAM_IN_SRC_REF))

        try:
            alignment = self.dfu.get_objects({'object_refs': [inref]})['data']
        except DFUError as e:
            self.__LOGGER.error('Logging stacktrace from workspace exception:\n' + e.data)
            raise

        # set the output dir
        uuid_str = str(uuid.uuid4())
        output_dir = os.path.join(self.scratch, 'download_' + uuid_str)
        self._mkdir_p(output_dir)

        file_ret = self.dfu.shock_to_file({'shock_id': alignment[0]['data']['file']['id'],
                                           'file_path': output_dir
                                           })
        if zipfile.is_zipfile(file_ret.get('file_path')):
            with zipfile.ZipFile(file_ret.get('file_path')) as z:
                z.extractall(output_dir)

        for f in glob.glob(output_dir + '/*.zip'):
            os.remove(f)

        bam_files = glob.glob(output_dir + '/*.bam')

        if len(bam_files) == 0:
            raise ValueError("Alignment object does not contain a bam file")

        for bam_file_path in bam_files:
            dir, file_name, file_base, file_ext = self._get_file_path_info(bam_file_path)
            if params.get(self.PARAM_IN_VALIDATE, False):
                validate_params = {'file_path': bam_file_path}
                if self._validate(validate_params) == 1:
                    raise Exception('{0} failed validation'.format(bam_file_path))

            if params.get(self.PARAM_IN_DOWNLOAD_BAI, False):
                bai_file = file_base + '.bai'
                bai_file_path = os.path.join(output_dir, bai_file)
                self.samtools.create_bai_from_bam(ifile=file_name, ipath=output_dir, ofile=bai_file)
                if not os.path.isfile(bai_file_path):
                    raise ValueError('Error creating {}'.format(bai_file_path))

            if params.get(self.PARAM_IN_DOWNLOAD_SAM, False):
                sam_file = file_base + '.sam'
                sam_file_path = os.path.join(output_dir, sam_file)
                self.samtools.convert_bam_to_sam(ifile=file_name, ipath=output_dir, ofile=sam_file)
                if not os.path.isfile(sam_file_path):
                    raise ValueError('Error creating {}'.format(sam_file_path))

        returnVal = {'destination_dir': output_dir,
                     'stats': alignment[0]['data']['alignment_stats']}

        #END download_alignment

        # At some point might do deeper type checking...
        if not isinstance(returnVal, dict):
            raise ValueError('Method download_alignment return value ' +
                             'returnVal is not type dict as required.')
        # return the results
        return [returnVal]

    def export_alignment(self, ctx, params):
        """
        Wrapper function for use by in-narrative downloaders to download alignments from shock *
        :param params: instance of type "ExportParams" (* Required input
           parameters for exporting a reads alignment string source_ref -
           object reference of alignment source. The object ref is
           'ws_name_or_id/obj_name_or_id' where ws_name_or_id is the
           workspace name or id and obj_name_or_id is the object name or id
           *) -> structure: parameter "source_ref" of String, parameter
           "exportSAM" of type "boolean" (A boolean - 0 for false, 1 for
           true. @range (0, 1)), parameter "exportBAI" of type "boolean" (A
           boolean - 0 for false, 1 for true. @range (0, 1)), parameter
           "validate" of type "boolean" (A boolean - 0 for false, 1 for true.
           @range (0, 1)), parameter "ignore" of list of String
        :returns: instance of type "ExportOutput" -> structure: parameter
           "shock_id" of String
        """
        # ctx is the context object
        # return variables are: output
        #BEGIN export_alignment

        inref = params.get(self.PARAM_IN_SRC_REF)
        if not inref:
            raise ValueError('{} parameter is required'.format(self.PARAM_IN_SRC_REF))

        if params.get(self.PARAM_IN_VALIDATE, False) or \
           params.get('exportBAI', False) or \
           params.get('exportSAM', False):
            """
            Need to validate or convert files. Use download_alignment
            """
            download_params = {}
            for key, val in params.items():
                download_params[key.replace('export', 'download')] = val

            download_retVal = self.download_alignment(ctx, download_params)[0]

            export_dir = download_retVal['destination_dir']

            # package and load to shock
            ret = self.dfu.package_for_download({'file_path': export_dir,
                                                 'ws_refs': [inref]
                                                 })
            output = {'shock_id': ret['shock_id']}
        else:
            """
            return shock id from the object
            """
            try:
                alignment = self.dfu.get_objects({'object_refs': [inref]})['data']
            except DFUError as e:
                self.__LOGGER.error('Logging stacktrace from workspace exception:\n' + e.data)
                raise
            output = {'shock_id': alignment[0]['data']['file']['id']}

        #END export_alignment

        # At some point might do deeper type checking...
        if not isinstance(output, dict):
            raise ValueError('Method export_alignment return value ' +
                             'output is not type dict as required.')
        # return the results
        return [output]
    def status(self, ctx):
        #BEGIN_STATUS
        returnVal = {'state': "OK",
                     'message': "",
                     'version': self.VERSION,
                     'git_url': self.GIT_URL,
                     'git_commit_hash': self.GIT_COMMIT_HASH}
        #END_STATUS
        return [returnVal]
