#include <iostream>
#include <cstring>
#include <unistd.h>
#include <arpa/inet.h>
#include <chrono>
#include <thread>
#include <cstdlib>

constexpr int PORT = 65432;

int main() {
    int sock = 0;
    struct sockaddr_in serv_addr{};
    char buffer[1024] = {0};

    sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) {
        perror("Socket creation error");
        return 1;
    }

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(PORT);

    if (inet_pton(AF_INET, "127.0.0.1", &serv_addr.sin_addr) <= 0) {
        perror("Invalid address / Address not supported");
        return 1;
    }

    if (connect(sock, (struct sockaddr*)&serv_addr, sizeof(serv_addr)) < 0) {
        perror("Connection Failed");
        return 1;
    }

    std::string message;
    while (true) {
        std::string message = "msg_" + std::to_string(std::rand() % 1000);
    
        send(sock, message.c_str(), message.length(), 0);
    
        memset(buffer, 0, sizeof(buffer));
        read(sock, buffer, sizeof(buffer) - 1);
    
        std::cout << "Response from the server: " << buffer << "\n";
    
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
}
