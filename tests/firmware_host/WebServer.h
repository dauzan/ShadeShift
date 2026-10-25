// Host stand-in for the ESP32 WebServer library (TEST ONLY). Requests come from the simulation script as
// "<t_ms> ##HTTP GET /data" lines and are served only when the firmware calls handleClient(), as on the board.
// Each response is printed as "##HTTP <code> <method> <path> <type>", the body, then "##HTTP-END".
#pragma once
#include <functional>
#include "arduino_stub.h"

enum HTTPMethod { HTTP_ANY, HTTP_GET, HTTP_POST };
struct SimHttp { std::string method, path; };
inline std::deque<SimHttp>& sim_http() { static std::deque<SimHttp> q; return q; }

class WebServer {
 public:
  explicit WebServer(int) {}
  void on(const char* uri, HTTPMethod m, std::function<void()> f) { routes_.push_back({uri, m, f}); }
  void on(const char* uri, std::function<void()> f) { on(uri, HTTP_ANY, f); }
  void begin() { running_ = true; }
  void stop() { running_ = false; }
  void handleClient() {
    sim_proses_direktif();
    if (sim_http().empty()) return;
    cur_ = sim_http().front();
    sim_http().pop_front();
    if (!running_) { std::printf("##HTTP - %s %s no-server\n##HTTP-END\n", cur_.method.c_str(), cur_.path.c_str()); return; }
    for (auto& r : routes_) {
      bool method_ok = r.m == HTTP_ANY || (r.m == HTTP_POST) == (cur_.method == "POST");
      if (r.uri == cur_.path && method_ok) { r.f(); return; }
    }
    send(404, "text/plain", "not found");
  }
  void send(int code, const char* type, const String& body) {
    std::printf("##HTTP %d %s %s %s\n%s\n##HTTP-END\n", code, cur_.method.c_str(), cur_.path.c_str(), type, body.c_str());
    fflush(stdout);
  }
  void send(int code, const char* type, const char* body) { send(code, type, String(body)); }

 private:
  struct Route { std::string uri; HTTPMethod m; std::function<void()> f; };
  std::vector<Route> routes_;
  bool running_ = false;
  SimHttp cur_;
};
