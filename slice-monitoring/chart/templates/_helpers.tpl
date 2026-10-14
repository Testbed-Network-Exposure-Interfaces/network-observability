{{/*
Expand the name of the chart.
*/}}
{{- define "slice-monitoring.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "slice-monitoring.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Component name, e.g. include "slice-monitoring.componentName" (dict "ctx" . "component" "prober")
*/}}
{{- define "slice-monitoring.componentName" -}}
{{- printf "%s-%s" (include "slice-monitoring.fullname" .ctx | trunc (int (sub 62 (len .component)))) .component | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "slice-monitoring.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Selector labels, e.g. include "slice-monitoring.selectorLabels" (dict "ctx" . "component" "prober")
*/}}
{{- define "slice-monitoring.selectorLabels" -}}
app.kubernetes.io/name: {{ include "slice-monitoring.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Common labels, same arguments as selectorLabels
*/}}
{{- define "slice-monitoring.labels" -}}
helm.sh/chart: {{ include "slice-monitoring.chart" .ctx }}
{{ include "slice-monitoring.selectorLabels" . }}
{{- if .ctx.Chart.AppVersion }}
app.kubernetes.io/version: {{ .ctx.Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
slice-monitoring/slice-id: {{ .ctx.Values.sliceId | quote }}
{{- end }}

{{/*
External URL path of the slice Grafana, e.g. /slice-monitoring/<sliceId>
*/}}
{{- define "slice-monitoring.grafanaPath" -}}
{{- printf "%s/%s" (trimSuffix "/" .Values.grafana.ingress.pathPrefix) (toString .Values.sliceId) }}
{{- end }}
