# Dockerfile to create a container with the IM service
FROM ubuntu:18.04
LABEL maintainer="Miguel Caballer <micafer1@upv.es>"
LABEL version="1.8.3"
LABEL description="Container image to run the IM service. (http://www.grycap.upv.es/im)"
EXPOSE 8899 8800

# Ensure system is up to date with mandatory python packages installed
RUN apt-get update && apt-get install --no-install-recommends -y python3-dbg python3-dev python3-pip openssh-client sshpass vim libmysqlclient20 python3-mysqldb && \
     pip3 install setuptools pip --upgrade -I && \
     apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && rm -rf ~/.cache/

# Install pip optional libraries
RUN pip3 install msrest msrestazure azure-common azure-mgmt-storage azure-mgmt-compute azure-mgmt-network azure-mgmt-resource azure-mgmt-dns azure-storage cheroot xmltodict pymongo

# Install IM
RUN apt-get update && apt-get install --no-install-recommends -y gcc libssl-dev libffi-dev libsqlite3-dev && \
     pip3 install pycrypto && \
     pip3 install IM==1.8.3 && \
     apt-get purge -y gcc libssl-dev libffi-dev libsqlite3-dev && \
     apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && rm -rf ~/.cache/

# Copy a ansible.cfg with correct minimum values
COPY ansible.cfg /etc/ansible/ansible.cfg

# Start IM service
CMD im_service.py
