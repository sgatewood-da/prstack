#!/usr/bin/env bash

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
MAGENTA='\033[1;35m'
CYAN='\033[1;36m'
GRAY='\033[1;37m'
NC='\033[0m' # No Color

function red() {
  printf "%b%b%b\n" "${RED}" "$@" "${NC}"
}

function green() {
  printf "%b%b%b\n" "${GREEN}" "$@" "${NC}"
}

function yellow() {
  printf "%b%b%b\n" "${YELLOW}" "$@" "${NC}"
}

function blue() {
  printf "%b%b%b\n" "${BLUE}" "$@" "${NC}"
}

function magenta() {
  printf "%b%b%b\n" "${MAGENTA}" "$@" "${NC}"
}

function cyan() {
  printf "%b%b%b\n" "${CYAN}" "$@" "${NC}"
}

function gray() {
  printf "%b%b%b\n" "${GRAY}" "$@" "${NC}"
}
