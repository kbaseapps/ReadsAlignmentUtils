import logging
import os
import re
from subprocess import Popen, PIPE

from .script_utils import log as log
from .script_utils import whereis


class SamTools:
    """
    This class wraps functions from samtools.

    The functions in this class pivot around the bam format. i.e if the user has
    a sam file, it is expected that the user will first convert the file to
    a bam format before performing any other operation from this class on the file.
    """

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        pass

    def _prepare_paths(self, ifile, ipath, ofile, opath, iext, oext):
        """
        setup input and output file paths and extensions
        """
        if ipath is None:
            raise Exception("Excepted an absolute path to input file to sam tools. Cannot be none.")
        if opath is not None and not opath.startswith('/'):
            raise Exception("Output path must be an absolute path. Provided: "+str(opath))
        if opath is None:
            opath = ipath
        if ofile is None:
            if ifile[-4:] == iext:
                ofile = ifile[:-4] + oext
            else:
                ofile = ifile + oext
        ifile = os.path.join(ipath, ifile)
        ofile = os.path.join(opath, ofile)

        return ifile, ofile, opath

    def _check_prog(self):
        """
        Check if samtools is present in the env
        """
        progPath = whereis('samtools')
        if not progPath:
            raise RuntimeError(None, '{0} command not found in your PATH '
                                     'environmental variable. {1}'.format(
                                         'samtools', os.environ.get('PATH', '')))

    def _extractAlignmentStatsInfo(self, stats):
        """
        Extract stats from line format and return as dict
        """
        lines = stats.splitlines()

        # patterns
        two_nums = re.compile(r'^(\d+) \+ (\d+)')
        # two_pcts = re.compile(r'\(([0-9.na\-]+)%:([0-9.na\-]+)%\)')
        # alignment rate
        m = two_nums.match(lines[0])
        total_qcpr = int(m.group(1))
        total_qcfr = int(m.group(2))
        total_read = total_qcpr + total_qcfr

        m = two_nums.match(lines[4])
        mapped_r = int(m.group(1))
        unmapped_r = int(total_read - mapped_r)

        if total_read == 0:
            self.logger.error('alignment stats don\'t look right. total_qcpr + total_qcfr = 0. '
                              'setting aligment_rate = 0.')
            alignment_rate = 0
        else:
            alignment_rate = float(mapped_r) / float(total_read) * 100.0
            if alignment_rate > 100:
                alignment_rate = 100.0

        # singletons
        m = two_nums.match(lines[10])
        singletons = int(m.group(1))
        m = two_nums.match(lines[8])
        properly_paired = int(m.group(1))
        multiple_alignments = 0

        # Create Workspace object
        stats_data = {
            # "alignment_id": sample_id,
            "alignment_rate": alignment_rate,
            "multiple_alignments": multiple_alignments,
            "properly_paired": properly_paired,
            "singletons": singletons,
            "total_reads": total_read,
            "unmapped_reads": unmapped_r,
            "mapped_reads": mapped_r
        }
        return stats_data

    def _is_valid(self, result, ignore):
        """
        Returns False if result contains errors not listed in the ignore list,
        else returns True
        :param result:
        :param ignore:
        :return:
        """
        if result is None:
            return True
        if ignore is None:
            ignore = ['xxx']  # ignore no errors

        if 'Exception' in result:
            return False

        lines = result.splitlines()
        for line in lines:
            m = re.search('(?<=ERROR:)\w+', line)
            if m is not None and m.group(0) not in ignore:
                return False

        return True

    def convert_sam_to_sorted_bam(self, ifile, ipath, ofile=None, opath=None,
                                  validate=False, ignore=['MATE_NOT_FOUND', 'MISSING_READ_GROUP',
                                                          'INVALID_MAPPING_QUALITY']):
        """
        Converts the specified sam file to a sorted bam file.

        throws exceptions if input file is missing, invalid or if the output file could
        not be written to disk

        :param ifile: sam file name
        :param ipath: absolute path to sam file.
        :param ofile: sorted bam file name. If None, ifile name is used with the
        extension '.sam' (if any) replaced with '.bam'
        :param opath: absolute path to sorted bam file. If None, ipath will be used
        :param validate: set to true if sam file needs to be validated. Default=False
        :param ignore: see validate() method param

        :returns 0 if successful, else 1
        """
        # prepare input and output file paths
        ifile, ofile, opath = self._prepare_paths(ifile, ipath, ofile, opath, '.sam', '.bam')

        # check if input file exists
        if not os.path.exists(ifile):
            raise RuntimeError(None, 'Input sam file does not exist: ' + str(ifile))

        # validate input sam file
        if validate and self.validate(ifile, ipath, ignore=ignore) == 1:
            return 1

        # convert
        self._check_prog()

        #   samtools view -bS ifile | samtools sort -l 9 -O BAM > ofile
        # samtools appears to operates on garbage-in-garbage out policy. i.e.
        # it does not validate input and always returns True. Hence output
        # value is not being checked.
        try:
            log('Converting sam to sorted bam for file: ' + str(ifile) + ' with cwd: ' + str(opath))
            sort = Popen(
                'samtools sort -l 9 -O BAM > {0}'.format(ofile),
                shell=True,
                stdin=PIPE,
                stdout=PIPE,
                cwd=opath)
            view = Popen('samtools view -bS {0}'.format(ifile), shell=True, stdout=sort.stdin, cwd=opath)
            result, stderr = sort.communicate()  # samtools always returns success
            view.wait()
        except Exception as ex:
            log(f'failed to convert {ifile} to {ofile}. {str(ex)}', logging.ERROR)

        return 0

    def convert_bam_to_sam(self, ifile, ipath, ofile=None, opath=None,
                           validate=False, ignore=['MATE_NOT_FOUND', 'MISSING_READ_GROUP',
                                                   'INVALID_MAPPING_QUALITY']):
        """
        Converts the specified bam file to a sam file.

        throws exceptions if input file is missing, invalid or if the output file could
        not be written to disk

        :param ifile: bam file name
        :param ipath: absolute path to bam file.
        :param ofile: sam file name. If None, ifile name is used with the
        extension '.bam' (if any) replaced with '.sam'
        :param opath: path to sam file. If None, ipath will be used
        :param validate: set to true if sam file needs to be validated. Default=False
        :param ignore: see validate() method param

        :returns 0 if successful, else 1
        """
        # prepare input and output file paths
        ifile, ofile, opath = self._prepare_paths(ifile, ipath, ofile, opath, '.sam', '.bam')

        # check if input file exists
        if not os.path.exists(ifile):
            raise RuntimeError(None, 'Input bam file does not exist: ' + str(ifile))

        # validate input sam file
        if validate and self.validate(ifile, ipath, ignore=ignore) == 1:
            return 1

        # convert
        self._check_prog()

        #   samtools view -h ifile > ofile
        # samtools appears to operates on garbage-in-garbage out policy. i.e.
        # it does not validate input and always returns True. Hence output
        # value is not being checked.
        try:
            log('Converting bam to sam for file: ' + str(ifile) + ' with output file: '+str(ofile)+' and cwd: ' + str(opath))
            convert = Popen('samtools view -h {0} > {1}'.format(ifile, ofile),
                            shell=True, stdin=PIPE, stdout=PIPE, cwd=opath)
            convert.communicate()
        except Exception as ex:
            log(f'failed to convert {ifile} to {ofile}. {str(ex)}', logging.ERROR)

        return 0

    def create_bai_from_bam(self, ifile, ipath, ofile=None, opath=None,
                            validate=False, ignore=['MATE_NOT_FOUND', 'MISSING_READ_GROUP',
                                                    'INVALID_MAPPING_QUALITY']):
        """
        creates a bai file from a bam file

        throws exceptions if input file is missing, invalid or if the output file could
        not be written to disk

        :param ifile: bam file name
        :param ipath: absolute path to bam file
        :param ofile: bai file name. If None, ifile name is used with the
        extension '.bam' (if any) replaced with '.bai'
        :param opath: path to bai file. If None, ipath will be used
        :param validate: set to true if sam file needs to be validated. Default=False
        :param ignore: see validate() method param

        :returns 0 if successful, else 1
        """
        # prepare input and output file paths
        ifile, ofile, opath = self._prepare_paths(ifile, ipath, ofile, opath, '.bam',
                                           '.bai')

        # check if input file exists
        if not os.path.exists(ifile):
            raise RuntimeError(None,
                               'Input bam file does not exist: ' + str(ifile))

        # validate input sam file
        if validate and self.validate(ifile, ipath, ignore=ignore) == 1:
            return 1

        # convert
        self._check_prog()

        #   samtools index ifile ofile
        # samtools appears to operates on garbage-in-garbage out policy. i.e.
        # it does not validate input and always returns True. Hence output
        # value is not being checked.
        try:
            log('Creating bai from bam for file: ' + str(ifile) + ' with output file: ' + str(ofile) + ' and cwd: ' + str(opath))
            create = Popen('samtools index {0} {1}'.format(ifile, ofile),
                           shell=True, stdin=PIPE, stdout=PIPE, cwd=opath)
            create.communicate()
        except Exception as ex:
            log(f'failed to convert {ifile} to {ofile}. {str(ex)}', logging.ERROR)
            return 1

        return 0

    def get_stats(self, ifile, ipath):
        """
        Generate simple statistics from a BAM file. The statistics collected include
        counts of aligned and unaligned reads as well as all records with no start
        coordinate.

        :param ifile: bam file name
        :param ipath: absolute path to bam file.
        """
        if not ipath.startswith('/'):
            raise Exception("Input path must be an absolute path. Provided: " + str(ipath))

        ifile = os.path.join(ipath, ifile)

        # check if input file exists
        if not os.path.exists(ifile):
            raise RuntimeError(None,
                               'Input bam file does not exist: ' + str(ifile))

        # get stats
        self._check_prog()

        #   samtools flagstat ifile
        # samtools appears to operates on garbage-in-garbage out policy. i.e.
        # it does not validate input and always returns True. Hence output
        # value is not being checked.
        stats = Popen('samtools flagstat {0}'.format(ifile),
                      shell=True, stdin=PIPE, stdout=PIPE)
        stats, stderr = stats.communicate()

        result = self._extractAlignmentStatsInfo(stats.decode())

        return result

    def validate(self, ifile, ipath,
                 ignore=['MATE_NOT_FOUND', 'MISSING_READ_GROUP',
                         'INVALID_MAPPING_QUALITY']):
        """
        Validates the input bam file. Logs the errors if errors are found

        :param ifile: bam file name
        :param ipath: absolute path to bam file.
        :param ignore: list of errors to ignore (see
        http://broadinstitute.github.io/picard/command-line-overview.html#ValidateSamFile)
        :returns 0 if successful, else 1
        """
        if not ipath.startswith('/'):
            raise Exception("Input path must be an absolute path. Provided: " + str(ipath))

        ifile = os.path.join(ipath, ifile)

        # check if input file exists
        if not os.path.exists(ifile):
            raise RuntimeError(None, 'Input file does not exist: ' + str(ifile))

        try:
            # java -jar picard.jar ValidateSamFile I=ifile MODE=SUMMARY
            validation = Popen(
                '/usr/lib/jvm/java-8-oracle/bin/java -jar '
                '/opt/picard/build/libs/picard.jar ValidateSamFile I={0} '
                'MODE=SUMMARY'.format(ifile),
                shell=True, stdin=PIPE, stdout=PIPE)
            result, stderr = validation.communicate()

            if self._is_valid(result.decode(), ignore):
                log(f'{ifile} passed validation', logging.INFO, self.logger)
                return 0
            else:
                log(f'{ifile} failed validation with errors: {result}',
                    logging.ERROR, self.logger)
                return 1

        except Exception as ex:
            log(f'{ifile} failed validation. {str(ex)}', logging.ERROR, self.logger)
            return 1
