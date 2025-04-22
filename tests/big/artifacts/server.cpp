#include <iostream>
#include <cstring>
#include <unistd.h>
#include <netinet/in.h>

constexpr int PORT = 65432;

int main() {
    int server_fd, client_socket;
    struct sockaddr_in address{};
    int opt = 1;
    int addrlen = sizeof(address);
    char buffer[1024];

    server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd == 0) {
        perror("socket failed");
        return 1;
    }

    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR | SO_REUSEPORT, &opt, sizeof(opt));

    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(PORT);

    if (bind(server_fd, (struct sockaddr*)&address, sizeof(address)) < 0) {
        perror("bind failed");
        return 1;
    }

    if (listen(server_fd, 1) < 0) {
        perror("listen");
        return 1;
    }

    std::cout << "The server is listening on the port " << PORT << "...\n";

    client_socket = accept(server_fd, (struct sockaddr*)&address, (socklen_t*)&addrlen);
    if (client_socket < 0) {
        perror("accept");
        return 1;
    }

    std::cout << "The client is connected.\n";

    while (true) {
        memset(buffer, 0, sizeof(buffer));
        ssize_t bytes_read = read(client_socket, buffer, sizeof(buffer) - 1);
        if (bytes_read <= 0) {
            std::cout << "The client has disconnected.\n";
            break;
        }

        std::cout << "Received: " << buffer << "\n";

        std::string response = "Server response: ";
        response += buffer;

        send(client_socket, response.c_str(), response.length(), 0);
    }

    close(client_socket);
    close(server_fd);
    return 0;
}
