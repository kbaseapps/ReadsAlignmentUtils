FROM kbase/kbase:sdkbase2.latest
MAINTAINER KBase Developer
# -----------------------------------------
# In this section, you can install any system dependencies required
# to run your App.  For instance, you could place an apt-get update or
# install line here, a git checkout to download code, or run any other
# installation scripts.

RUN apt-get update && apt-get install -y sysstat

# Here we install a python coverage tool and an
# https library that is out of date in the base image.

RUN pip install coverage

# Install Samtools
RUN cd /opt \
    && wget https://github.com/samtools/samtools/releases/download/1.4.1/samtools-1.4.1.tar.bz2 \
    && tar xvjf samtools-1.4.1.tar.bz2 \
    && rm -f samtools-1.4.1.tar.bz2 \
    && cd samtools-1.4.1 \
    && ./configure \
    && make \
    && make install

ENV PATH $PATH:/opt/samtools-1.4.1

# Install Java.
RUN \
  echo oracle-java8-installer shared/accepted-oracle-license-v1-1 select true | debconf-set-selections \
  && add-apt-repository -y ppa:webupd8team/java \
  && apt-get update \
  && apt-get install -y oracle-java8-installer \
  && rm -rf /var/lib/apt/lists/* \
  && rm -rf /var/cache/oracle-jdk8-installer


# reset JAVA_HOME variable
ENV JAVA_HOME /usr/lib/jvm/java-8-oracle

# Download and install Gradle
RUN \
    cd /opt \
    && curl -L https://services.gradle.org/distributions/gradle-2.5-bin.zip -o gradle-2.5-bin.zip \
    && unzip gradle-2.5-bin.zip \
    && rm gradle-2.5-bin.zip

# Export some environment variables
ENV GRADLE_HOME=/opt/gradle-2.5
ENV PATH=$PATH:$GRADLE_HOME/bin

# Install Picard
RUN cd /opt \
    && javac -version \
    && java -version \
    && git clone --depth 1 https://github.com/broadinstitute/picard.git \
    && cd picard \
    && ./gradlew shadowJar \
    && ls build/libs

RUN pip install pysam
# -----------------------------------------

COPY ./ /kb/module
RUN mkdir -p /kb/module/work
RUN chmod -R a+rw /kb/module

WORKDIR /kb/module

RUN make all

ENTRYPOINT [ "./scripts/entrypoint.sh" ]

CMD [ ]
