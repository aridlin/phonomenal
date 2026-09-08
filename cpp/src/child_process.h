#pragma once
#include <filesystem>
#include <stop_token>
#include <string>
#include <vector>
int RunChild(const std::vector<std::string>& args,const std::filesystem::path& cwd,const std::filesystem::path& log,std::stop_token stop);
