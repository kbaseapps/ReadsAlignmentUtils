--Changes__
### Version 0.3.4
- Added retry logic to _check_job to address issues with BADSTATUSCODE

### Version 0.3.1
- Fixed issue with download directory name. Uses uuid4 to have a unique directory name.

### Version 0.2.1
- Fixed issue with samtools writing tmp files to current working directory when input files are very large.

### Version 0.1.0
- download_alignment() returns 'destination_dir' containing all the files in the alignment object, instead of
'bam_file_path'. This was made to download legacy RNASeqAlignment objects which contained more than one file.
- Bumped up the version for release

### Version 0.0.2

### Version 0.0.1
__Initial version of the module to upload, download, validate and export RNASeq Alignment data.__
- Validates, saves and retrieves the alignment data file generated either by BowTie2, TopHat2 or HISAT2 App.
- The data is saved in the sorted BAM format. If the input given is in SAM format, it is converted to sorted BAM before saving.
- This module also generates and saves aligner stats from the file provided for upload.
- During download and export, the user has the option to download in BAM, SAM and BAI formats.
__Changes__
- wrapped samtools-v1.4.1 and picard validation for sam/bam alignment formats (latest from github)







