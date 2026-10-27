# Reference CICFlowMeter: the corrected fork by Engelen et al. at commit 13a0615, the version the
# training data was made with. Only for the flow extractor's parity test (scripts/validate_flowmeter.py);
# not part of the app. It reads classic pcap files with Ethernet frames, as the original tool does.
#
#   docker build -f docker/cicflowmeter.Dockerfile -t ai-ids-cicflowmeter docker
#   docker run --rm -v "<dir with the capture>:/data" ai-ids-cicflowmeter /data/capture.pcap /data/
#   -> /data/capture.pcap_Flow.csv
FROM eclipse-temurin:8-jdk-jammy

ARG REPO=https://github.com/GintsEngelen/CICFlowMeter.git
ARG COMMIT=13a0615

RUN apt-get update \
    && apt-get install -y --no-install-recommends git libpcap0.8 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s libpcap.so.0.8 /usr/lib/x86_64-linux-gnu/libpcap.so    # jnetpcap links the unversioned name

WORKDIR /opt
RUN git clone --quiet "$REPO" cfm && git -C cfm checkout --quiet "$COMMIT"

# The dependencies the command-line tool needs, at the versions of its build.gradle
RUN mkdir lib && cd lib && for jar in \
        org/apache/commons/commons-math3/3.5/commons-math3-3.5.jar \
        org/apache/commons/commons-lang3/3.6/commons-lang3-3.6.jar \
        commons-io/commons-io/2.5/commons-io-2.5.jar \
        org/apache/tika/tika-core/1.17/tika-core-1.17.jar \
        org/slf4j/slf4j-api/1.7.25/slf4j-api-1.7.25.jar \
        org/slf4j/slf4j-simple/1.7.25/slf4j-simple-1.7.25.jar; \
    do curl -fsSLO "https://repo1.maven.org/maven2/$jar"; done

# Compile only what the command-line entry point uses (javac follows the references), not the GUI
RUN mkdir classes && javac -nowarn -encoding UTF-8 -d classes -sourcepath cfm/src/main/java \
        -cp "lib/*:cfm/jnetpcap/linux/jnetpcap-1.4.r1425/jnetpcap.jar" \
        cfm/src/main/java/cic/cs/unb/ca/ifm/Cmd.java

# jnetpcap jar r1425 with the r1500 native library, as the project's own distribution ships them
ENTRYPOINT ["java", "-Djava.library.path=/opt/cfm/jnetpcap/linux/jnetpcap-1.4.r1500", \
            "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn", \
            "-cp", "/opt/classes:/opt/lib/*:/opt/cfm/jnetpcap/linux/jnetpcap-1.4.r1425/jnetpcap.jar", \
            "cic.cs.unb.ca.ifm.Cmd"]
