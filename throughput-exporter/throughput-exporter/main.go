package main

import (
	"flag"
	"log"
	"net/http"
	"strconv"
	"strings"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcap"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func capturePackets(iface string) {
	// 1. Define Metrics
	ifaceprefix := strings.ReplaceAll(iface, "-", "_")
	var (
		bytesPerIP = prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Name: ifaceprefix + "_throughput_bytes_total",
				Help: "Total bytes seen per source/dest MAC and IP, with protocol",
			},
			[]string{"src_mac", "dst_mac", "src_ip", "dst_ip", "proto"},
		)
		packetsPerIP = prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Name: ifaceprefix + "_throughput_packets_total",
				Help: "Total packets seen per source/dest MAC and IP, with protocol",
			},
			[]string{"src_mac", "dst_mac", "src_ip", "dst_ip", "proto"},
		)
	)

	// 2. Register metrics with Prometheus
	prometheus.MustRegister(bytesPerIP)
	prometheus.MustRegister(packetsPerIP)

	handle, err := pcap.OpenLive(iface, 1600, true, pcap.BlockForever)
	if err != nil {
		log.Fatalf("Failed to open device %s: %v", iface, err)
	}
	defer handle.Close()

	packetSource := gopacket.NewPacketSource(handle, handle.LinkType())
	for packet := range packetSource.Packets() {
		// 3. Parse and update metrics per packet
		ipLayer := packet.NetworkLayer()
		if ipLayer == nil {
			continue
		}
		src := ipLayer.NetworkFlow().Src().String()
		dst := ipLayer.NetworkFlow().Dst().String()
		proto := protoName(packet)
		size := float64(len(packet.Data()))

		srcMAC, dstMAC := "unknown", "unknown"
		if ll := packet.LinkLayer(); ll != nil {
			if eth, ok := ll.(*layers.Ethernet); ok {
				srcMAC = eth.SrcMAC.String()
				dstMAC = eth.DstMAC.String()
			}
		}

		bytesPerIP.WithLabelValues(srcMAC, dstMAC, src, dst, proto).Add(size)
		packetsPerIP.WithLabelValues(srcMAC, dstMAC, src, dst, proto).Inc()
	}
}

func protoName(packet gopacket.Packet) string {
	if nl := packet.NetworkLayer(); nl != nil {
		switch v := nl.(type) {
		case *layers.IPv4:
			return strconv.Itoa(int(v.Protocol))
		case *layers.IPv6:
			return strconv.Itoa(int(v.NextHeader))
		}
	}
	return "unknown"
}

func main() {
	ifaceFlag := flag.String("iface", "lo", "interface to capture on")
	portFlag := flag.Int("port", 9200, "port to listen on")
	flag.Parse()

	iface := strings.TrimSpace(*ifaceFlag)
	port := strconv.Itoa(*portFlag)
	log.Printf("Starting capture on interface %s, exposing port %s", iface, port)

	// 4. Start packet capture in background
	go capturePackets(iface)

	// 5. Expose /metrics endpoint
	http.Handle("/metrics", promhttp.Handler())
	err := http.ListenAndServe(":"+port, nil)
	if err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
