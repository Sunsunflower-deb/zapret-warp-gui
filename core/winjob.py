"""«Умри вместе с приложением» для дочернего процесса — Windows Job Object.

Зачем: `winws.exe` запускается из GUI и продолжает жить после его закрытия.
Получается осиротевший процесс, который держит WinDivert и дурит трафик, а
пользователь уверен, что «всё выключил».

Job Object с `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` решает это на уровне ОС:
как только закрывается последний handle джобы (то есть при выходе процесса,
который её создал), все процессы внутри джобы уничтожаются.

Модуль используется только из GUI. CLI (`cli.py start`) НЕ должен привязывать
winws к джобе: CLI завершается сразу, и туннель умер бы вместе с ним.
"""
import os

# Handle держим в модуле: пока он жив, жива и джоба.
_handle = None

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9


def supported():
    return os.name == "nt"


def _ctypes():
    import ctypes

    return ctypes


def _structures(ctypes):
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMIT),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return EXTENDED_LIMIT


def attach(pid):
    """Поместить процесс `pid` в job с KILL_ON_JOB_CLOSE. True при успехе.

    Ошибки не фатальны: если ОС не даёт (старая Windows, вложенные джобы
    запрещены политикой), приложение просто работает как раньше.
    """
    global _handle
    if not supported():
        return False
    if _handle is None:
        _handle = _create_job()
        if _handle is None:
            return False
    ctypes = _ctypes()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process = kernel32.OpenProcess(0x1F0FFF, False, int(pid))  # PROCESS_ALL_ACCESS
    if not process:
        return False
    try:
        return bool(kernel32.AssignProcessToJobObject(_handle, process))
    finally:
        kernel32.CloseHandle(process)


def _create_job():
    ctypes = _ctypes()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    extended = _structures(ctypes)()
    extended.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(extended),
        ctypes.sizeof(extended),
    )
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return job


def release():
    """Закрыть handle джобы → все процессы внутри будут убиты.

    Нужно для явного «остановить всё» и для тестов.
    """
    global _handle
    if not supported() or _handle is None:
        return False
    ctypes = _ctypes()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle(_handle)
    _handle = None
    return True


def active():
    return _handle is not None
