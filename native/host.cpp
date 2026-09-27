#include "side_galaxy_core.h"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <charconv>
#include <limits>
#include <cstring>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <thread>
#if defined(__linux__)
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>
#include <unistd.h>
#endif

using nlohmann::json;
namespace fs = std::filesystem;
namespace {
std::string read(const fs::path& p, size_t bound=262144) {
    std::ifstream in(p); if(!in) return {};
    std::string s(bound, '\0'); in.read(s.data(), static_cast<std::streamsize>(bound)); s.resize(static_cast<size_t>(in.gcount())); return s;
}
bool counter(const std::string& text, unsigned long long& value) {
    const auto result=std::from_chars(text.data(),text.data()+text.size(),value);
    return result.ec==std::errc{} && result.ptr==text.data()+text.size();
}
long long number(const fs::path& p) {
    std::istringstream in(read(p,128)); std::string token,extra; unsigned long long value=0;
    if(!(in>>token) || in>>extra || !counter(token,value) || value>static_cast<unsigned long long>(std::numeric_limits<long long>::max()))return -1;
    return static_cast<long long>(value);
}
json sample(const json& input) {
    json out={{"source","unavailable"},{"sampled_at",std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count()},
      {"cpu_percent",nullptr},{"cpu_frequency_mhz",nullptr},{"temperature_celsius",nullptr},{"memory_total_mib",nullptr},
      {"memory_available_mib",nullptr},{"disk_total_bytes",nullptr},{"disk_available_bytes",nullptr},{"throttled",nullptr},{"cgroup_available",false},{"per_cpu",json::array()}};
#if defined(__linux__)
    out["source"]="linux";
#endif
    // Local-only fixture roots support parser checks; network clients cannot set them.
    fs::path proc=input.value("proc_root","/proc"), sys=input.value("sys_root","/sys");
    std::istringstream mem(read(proc/"meminfo")); std::string line;
    while(std::getline(mem,line)) {std::istringstream row(line);std::string key,text,unit,extra;unsigned long long value=0;
      if(!(row>>key>>text>>unit) || row>>extra || unit!="kB" || !counter(text,value))continue;
      if(key=="MemTotal:") out["memory_total_mib"]=value/1024.0;
      if(key=="MemAvailable:") out["memory_available_mib"]=value/1024.0;}
    static std::mutex guard; std::lock_guard lock(guard);
    static std::map<std::string,std::pair<unsigned long long,unsigned long long>> previous;
    std::istringstream stat(read(proc/"stat")); double frequency=0;int frequencies=0;
    while(std::getline(stat,line)) {
      std::istringstream row(line);std::string cpu;row>>cpu;
      if(cpu!="cpu" && !(cpu.size()>3 && cpu.rfind("cpu",0)==0 && std::all_of(cpu.begin()+3,cpu.end(),[](char c){return c>='0'&&c<='9';}))) continue;
      unsigned long long total=0,idle=0,v=0; int fields=0;bool valid=true;std::string text;
      while(fields<8 && row>>text){
        if(!counter(text,v) || v>std::numeric_limits<unsigned long long>::max()-total){valid=false;break;}
        total+=v;if(fields==3||fields==4)idle+=v;fields++;
      }
      auto key=proc.string()+":"+cpu;
      if(!valid || fields<4){previous.erase(key);continue;}
      unsigned long long id=0;
      if(cpu!="cpu" && (!counter(cpu.substr(3),id)||id>1023))continue;
      json percent=nullptr; auto it=previous.find(key);
      if(it!=previous.end() && total>it->second.first && idle>=it->second.second) {
        auto delta=total-it->second.first, rest=idle-it->second.second;
        if(rest<=delta) percent=100.0*static_cast<double>(delta-rest)/static_cast<double>(delta);
      }
      previous[key]={total,idle}; if(previous.size()>4096) previous.clear();
      if(cpu=="cpu") out["cpu_percent"]=percent;
      else {
        auto f=number(sys/"devices/system/cpu"/cpu/"cpufreq/scaling_cur_freq");
        json mhz=f>=0?json(f/1000.0):json(nullptr);if(f>=0){frequency+=f/1000.0;frequencies++;}
        out["per_cpu"].push_back({{"id",id},{"percent",percent},{"frequency_mhz",mhz}});
      }
    }
    if(frequencies)out["cpu_frequency_mhz"]=frequency/frequencies;
    // Expose the hottest measured zone; unsupported sensors remain null.
    std::error_code ec; auto thermal=sys/"class/thermal";
    if(fs::is_directory(thermal,ec))for(const auto& e:fs::directory_iterator(thermal,ec)){
      if(e.path().filename().string().rfind("thermal_zone",0)!=0)continue;
      auto t=number(e.path()/"temp"); if(t<0||t>250000)continue;
      double value=t/1000.0;if(out["temperature_celsius"].is_null()||value>out["temperature_celsius"].get<double>())out["temperature_celsius"]=value;
    }
#if defined(__linux__)
    struct statvfs disk{}; auto path=input.value("disk_path",std::string("."));
    if(statvfs(path.c_str(),&disk)==0){out["disk_total_bytes"]=static_cast<unsigned long long>(disk.f_blocks)*disk.f_frsize;out["disk_available_bytes"]=static_cast<unsigned long long>(disk.f_bavail)*disk.f_frsize;}
#endif
    return out;
}
#if defined(__linux__)
void write(const fs::path& p,const std::string& s){std::ofstream out(p);if(!out || !(out<<s) || !out.flush())throw std::runtime_error("Resource control write failed");}
fs::path current_group(){std::istringstream rows(read("/proc/self/cgroup"));std::string line;while(std::getline(rows,line))if(line.rfind("0::/",0)==0)return fs::path("/sys/fs/cgroup")/line.substr(4);throw std::runtime_error("Unified cgroup unavailable");}
fs::path root_group(const json& input){
    auto root=fs::canonical(input.at("root").get<std::string>());auto current=fs::canonical(current_group());
    if(current.filename()=="manager")current=current.parent_path();
    struct statfs info{};
    if(root!=current || root==fs::path("/sys/fs/cgroup") || statfs(root.c_str(),&info)!=0 || info.f_type!=0x63677270)
      throw std::runtime_error("Resource root is not the delegated agent scope");
    return root;
}
bool has_word(const std::string& text,const std::string& word){std::istringstream in(text);std::string value;while(in>>value)if(value==word)return true;return false;}
fs::path run_group(const json& input){
    auto name=input.at("name").get<std::string>();
    if(name.size()!=39 || name.rfind("sg-",0)!=0 || !std::all_of(name.begin()+3,name.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f')||c=='-';}))throw std::runtime_error("Invalid resource scope identity");
    auto root=root_group(input);auto result=root/name;
    if(fs::is_symlink(result))throw std::runtime_error("Invalid resource scope type");
    return result;
}
unsigned long long inode(const fs::path& p){struct stat st{};if(lstat(p.c_str(),&st)!=0||!S_ISDIR(st.st_mode))throw std::runtime_error("Resource scope missing");return st.st_ino;}
std::set<int> cpu_set(const std::string& value){std::set<int> result;std::istringstream in(value);std::string part;while(std::getline(in,part,',')) {auto split=part.find('-');int lo=std::stoi(part),hi=split==std::string::npos?lo:std::stoi(part.substr(split+1));if(lo<0||hi<lo||hi>1023)throw std::runtime_error("Invalid CPU set");for(int c=lo;c<=hi;c++)result.insert(c);}return result;}
json resource(const std::string& op,const json& input){
    if(op=="prepare"){
      auto root=root_group(input);auto controllers=read(root/"cgroup.controllers");
      if(!has_word(controllers,"memory")||!has_word(controllers,"cpuset"))throw std::runtime_error("Memory and cpuset delegation required");
      std::istringstream processes(read(root/"cgroup.procs"));int pid=0;while(processes>>pid)if(pid!=getpid())throw std::runtime_error("Delegated root contains other processes");
      fs::create_directory(root/"manager");write(root/"manager/cgroup.procs",std::to_string(getpid()));
      write(root/"cgroup.subtree_control","+memory +cpuset");
      return {{"available",true}};
    }
    auto path=run_group(input);
    if(op=="create"){
      if(!fs::create_directory(path))throw std::runtime_error("Resource scope already exists");
      try{
        const auto cpus=input.at("cpus");if(!cpus.is_array()||cpus.empty()||cpus.size()>1024)throw std::runtime_error("CPU set required");
        auto allowed=cpu_set(read(path.parent_path()/"cpuset.cpus.effective"));std::set<int> selected;std::string list;
        for(const auto& v:cpus){if(!v.is_number_integer())throw std::runtime_error("Invalid CPU identifier");int c=v.get<int>();if(!allowed.count(c)||!selected.insert(c).second)throw std::runtime_error("CPU outside delegated set");if(!list.empty())list+=",";list+=std::to_string(c);}
        auto memory=input.at("memory_bytes").get<unsigned long long>();if(memory<128ULL*1024*1024||memory>16777216ULL*1024*1024)throw std::runtime_error("Invalid memory budget");
        write(path/"cpuset.mems",read(path.parent_path()/"cpuset.mems.effective"));write(path/"cpuset.cpus",list);
        write(path/"memory.max",std::to_string(memory));write(path/"memory.oom.group","1");
        if(fs::exists(path/"memory.swap.max"))write(path/"memory.swap.max","0");
        int pid=input.at("pid").get<int>();std::istringstream rows(read(fs::path("/proc")/std::to_string(pid)/"status"));std::string line;bool child=false;
        while(std::getline(rows,line))if(line.rfind("PPid:",0)==0)child=std::stoi(line.substr(5))==getpid();
        if(!child)throw std::runtime_error("Resource placement requires a direct child");
        // Build the receipt before moving the child: a later allocation or inode
        // lookup failure must not lose the scope identity after placement.
        json receipt={{"name",path.filename().string()},{"inode",inode(path)},{"memory_limit_bytes",memory},{"cpus",cpus},{"enforcement","cgroup-v2"}};
        write(path/"cgroup.procs",std::to_string(pid));
        return receipt;
      }catch(...){std::error_code ec;fs::remove(path,ec);throw;}
    }
    if(op=="finish"){
      if(inode(path)!=input.at("inode").get<unsigned long long>())throw std::runtime_error("Resource scope identity changed");
      auto memory_events=read(path/"memory.events");json stats=json::object();std::istringstream events(memory_events);std::string key;unsigned long long count;
      while(events>>key>>count)stats[key]=count;
      if(read(path/"cgroup.events").find("populated 1")!=std::string::npos)write(path/"cgroup.kill","1");
      auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
      while(read(path/"cgroup.events").find("populated 0")==std::string::npos){if(std::chrono::steady_clock::now()>=end)return {{"empty",false},{"removed",false},{"memory_events",stats}};std::this_thread::sleep_for(std::chrono::milliseconds(20));}
      auto peak=number(path/"memory.peak");std::error_code ec;bool removed=fs::remove(path,ec);
      return {{"empty",true},{"removed",removed},{"memory_peak_bytes",peak<0?json(nullptr):json(peak)},{"memory_events",stats}};
    }
    throw std::runtime_error("Unknown host operation");
}
#endif
}
extern "C" SG_CORE_API char* sg_host_call(const char* operation,const char* payload) {
    // No exception, including allocation failure while encoding an error, may
    // cross the C ABI into the agent's ctypes caller.
    try {
      json result;
      try {
        if(!operation || !payload || std::strlen(operation)>64 || std::strlen(payload)>1024*1024)
          throw std::runtime_error("Invalid host call arguments");
        auto input=json::parse(payload);if(!input.is_object())throw std::runtime_error("Invalid host payload");
        std::string op=operation;json value;
        if(op=="sample")value=sample(input);
#if defined(__linux__)
        else value=resource(op,input);
#else
        else throw std::runtime_error("Linux resource controls unavailable");
#endif
        result={{"ok",true},{"value",value}};
      }catch(...){result={{"ok",false},{"error",{{"kind","invalid"},{"message","Host operation failed; inspect local delegation and resource state"}}}};}
      auto text=result.dump();auto out=static_cast<char*>(std::malloc(text.size()+1));
      if(out)std::memcpy(out,text.c_str(),text.size()+1);
      return out;
    }catch(...){return nullptr;}
}
