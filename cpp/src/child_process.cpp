#include "child_process.h"
#include <chrono>
#include <stdexcept>
#include <thread>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
static std::wstring wide(const std::string &text) {
  int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                              static_cast<int>(text.size()), nullptr, 0);
  if (n <= 0 && !text.empty())
    throw std::runtime_error("Invalid UTF-8 process argument");
  std::wstring out(n, 0);
  MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                      static_cast<int>(text.size()), out.data(), n);
  return out;
}
static std::wstring quoted(const std::string &text) {
  std::wstring out = L"\"";
  std::size_t slashes = 0;
  for (wchar_t c : wide(text)) {
    if (c == L'\\') {
      ++slashes;
      continue;
    }
    out.append(slashes * (c == L'"' ? 2 : 1), L'\\');
    slashes = 0;
    if (c == L'"')
      out += L'\\';
    out += c;
  }
  out.append(slashes * 2, L'\\');
  out += L'"';
  return out;
}
int RunChild(const std::vector<std::string> &args,
             const std::filesystem::path &cwd, const std::filesystem::path &log,
             std::stop_token stop) {
  std::wstring command;
  for (const auto &a : args) {
    if (!command.empty())
      command += L' ';
    command += quoted(a);
  }
  SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
  HANDLE file =
      CreateFileW(log.c_str(), GENERIC_WRITE, FILE_SHARE_READ, &security,
                  CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE)
    throw std::runtime_error("Cannot open builder log");
  STARTUPINFOW si{};
  si.cb = sizeof(si);
  si.dwFlags = STARTF_USESTDHANDLES;
  si.hStdOutput = file;
  si.hStdError = file;
  si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
  PROCESS_INFORMATION pi{};
  HANDLE job = CreateJobObjectW(nullptr, nullptr);
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
  limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
  SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits,
                          sizeof(limits));
  bool ok = CreateProcessW(nullptr, command.data(), nullptr, nullptr, TRUE,
                           CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr,
                           cwd.c_str(), &si, &pi);
  CloseHandle(file);
  if (!ok) {
    CloseHandle(job);
    throw std::runtime_error("Cannot start builder executable");
  }
  AssignProcessToJobObject(job, pi.hProcess);
  ResumeThread(pi.hThread);
  while (WaitForSingleObject(pi.hProcess, 50) == WAIT_TIMEOUT)
    if (stop.stop_requested()) {
      TerminateJobObject(job, 2);
      break;
    }
  WaitForSingleObject(pi.hProcess, INFINITE);
  DWORD code = 0;
  GetExitCodeProcess(pi.hProcess, &code);
  CloseHandle(pi.hThread);
  CloseHandle(pi.hProcess);
  CloseHandle(job);
  return static_cast<int>(code);
}
#else
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
int RunChild(const std::vector<std::string> &args,
             const std::filesystem::path &cwd, const std::filesystem::path &log,
             std::stop_token stop) {
  std::vector<char *> argv;
  for (const auto &a : args)
    argv.push_back(const_cast<char *>(a.c_str()));
  argv.push_back(nullptr);
  posix_spawn_file_actions_t actions;
  posix_spawn_file_actions_init(&actions);
  posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, log.c_str(),
                                   O_WRONLY | O_CREAT | O_TRUNC, 0600);
  posix_spawn_file_actions_adddup2(&actions, STDOUT_FILENO, STDERR_FILENO);
  posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null",
                                   O_RDONLY, 0);
  posix_spawn_file_actions_addchdir_np(&actions, cwd.c_str());
  posix_spawnattr_t attr;
  posix_spawnattr_init(&attr);
  posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETPGROUP);
  posix_spawnattr_setpgroup(&attr, 0);
  pid_t pid{};
  int rc = posix_spawnp(&pid, argv[0], &actions, &attr, argv.data(), environ);
  posix_spawn_file_actions_destroy(&actions);
  posix_spawnattr_destroy(&attr);
  if (rc)
    throw std::runtime_error("Cannot start builder executable (" +
                             std::to_string(rc) + ")");
  int status = 0;
  while (waitpid(pid, &status, WNOHANG) == 0) {
    if (stop.stop_requested()) {
      kill(-pid, SIGTERM);
      for (int i = 0; i < 20; ++i) {
        if (waitpid(pid, &status, WNOHANG) == pid)
          return 2;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
      }
      kill(-pid, SIGKILL);
      waitpid(pid, &status, 0);
      return 2;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
  }
  return WIFEXITED(status) ? WEXITSTATUS(status) : 2;
}
#endif
