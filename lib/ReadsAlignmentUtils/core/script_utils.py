import logging
import os
import subprocess
import traceback


'''
A utility python module containing a set of methods necessary for this kbase
module.
'''

LEVELS = {'debug': logging.DEBUG,
          'info': logging.INFO,
          'warning': logging.WARNING,
          'error': logging.ERROR,
          'critical': logging.CRITICAL}


def log(message, level=logging.INFO, logger=None):
    if logger is None:
        if level == logging.DEBUG:
            print('\nDEBUG: ' + message + '\n')
        elif level == logging.INFO:
            print('\nINFO: ' + message + '\n')
        elif level == logging.WARNING:
            print('\nWARNING: ' + message + '\n')
        elif level == logging.ERROR:
            print('\nERROR: ' + message + '\n')
        elif level == logging.CRITICAL:
            print('\nCRITICAL: ' + message + '\n')
    else:
        logger.log(level, '\n' + message + '\n')


def whereis(program):
    """
    returns path of program if it exists in your ``$PATH`` variable or `
    `None`` otherwise
    """
    for path in os.environ.get('PATH', '').split(':'):
        if os.path.exists(os.path.join(path, program)) and not os.path.isdir(
                os.path.join(path, program)):
            return os.path.join(path, program)
    return None


def runProgram(logger=None,
               progName=None,
               argStr=None,
               script_dir=None,
               working_dir=None):
    """
    Convenience func to handle calling and monitoring output of external programs.

    :param progName: name of system program command
    :param argStr: string containing command line options for ``progName``

    :returns: subprocess.communicate object
    """

    # Ensure program is callable.
    if script_dir is not None:
        progPath = os.path.join(script_dir, progName)
    else:
        progPath = progName
    progPath = whereis(progName)
    if not progPath:
        raise RuntimeError(
            None,
            '{0} command not found in your PATH environmental variable. {1}'.format(
                progName,
                os.environ.get(
                    'PATH',
                    '')))

    # Construct shell command
    cmdStr = "%s %s" % (progPath, argStr)
    if logger is not None:
        logger.info("Executing : " + cmdStr)
    if working_dir is None:
        logger.info("Executing: " + cmdStr + " on cwd")
    else:
        logger.info("Executing: " + cmdStr + " on " + working_dir)

    # Set up process obj
    process = subprocess.Popen(cmdStr,
                               shell=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               cwd=working_dir)
    # Get results
    result, stderr = process.communicate()
    # print result
    # print stderr
    # keep this until your code is stable for easier debugging
    if logger is not None and result is not None and len(result) > 0:
        logger.info(result)
    else:
        print(result)
    if logger is not None and stderr is not None and len(stderr) > 0:
        logger.info(stderr)
    else:
        print(stderr)

    # Check returncode for success/failure
    if process.returncode != 0:
        raise Exception("Command execution failed  {0}".format(
            "".join(traceback.format_exc())))

    # Return result
    return {"result": result, "stderr": stderr}


def check_sys_stat(logger):
    check_disk_space(logger)
    check_memory_usage(logger)
    check_cpu_usage(logger)


def check_disk_space(logger):
    runProgram(logger=logger, progName="df", argStr="-h")


def check_memory_usage(logger):
    runProgram(logger=logger, progName="vmstat", argStr="-s")


def check_cpu_usage(logger):
    runProgram(logger=logger, progName="mpstat", argStr="-P ALL")
