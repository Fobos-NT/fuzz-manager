FROM alpine:3.14

# install python and dependencies
RUN apk add python3
RUN apk add py-pip
RUN apk add git
RUN pip3 install requests python-gitlab
