FROM mcr.microsoft.com/playwright:v1.64.1-noble

RUN npm install -g playwright@1.64.1

USER pwuser
WORKDIR /home/pwuser
EXPOSE 3000

ENTRYPOINT ["timeout", "900", "playwright", "run-server", "--host", "0.0.0.0", "--port", "3000", "--unsafe", "--max-clients", "1"]
