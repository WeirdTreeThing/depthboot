#!/usr/bin/env python3

import os
from shutil import rmtree as rmdir
from pathlib import Path
import sys
import argparse
from urllib.request import urlretrieve
import subprocess as sp
from os import system as bash
from threading import Thread
from urllib.error import URLError
from time import sleep


# parse arguments from the cli. Only for testing/advanced use. 95% of the arguments are handled by the user_input script
def process_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--local-path', dest="local_path",
                        help="Local path for kernel files, to use instead of downloading from github." +
                             "(Unsigned kernels only)")
    parser.add_argument("--dev", action="store_true", dest="dev_build", default=False,
                        help="Use latest dev build. May be unstable.")
    parser.add_argument("--alt", action="store_true", dest="alt", default=False,
                        help="Use alt kernel. Only for older devices.")
    parser.add_argument("--exp", action="store_true", dest="exp", default=False,
                        help="Use experimental 5.15 kernel.")
    parser.add_argument("--mainline", action="store_true", dest="mainline", default=False,
                        help="Use mainline linux kernel instead of modified chromeos kernel.")
    return parser.parse_args()


# Clean /tmp from eupnea files
def prepare_host() -> None:
    print("\033[96m" + "Preparing host system" + "\033[0m")
    print("Creating mnt points")
    bash("umount -lf /mnt/eupnea_rootfs")  # just in case
    rmdir("/mnt/eupnea_rootfs", ignore_errors=True)
    Path("/mnt/eupnea_rootfs").mkdir(parents=True, exist_ok=True)

    print("Remounting USB/SD-card")
    bash(f"umount {device}1")
    bash(f"umount {device}2")
    bash(f"mount {device}2 /mnt/eupnea_rootfs")

    print("Creating /tmp/eupnea-update")
    rmdir("/tmp/eupnea-update", ignore_errors=True)
    Path("/tmp/eupnea-update").mkdir()
    print("Installing necessary packages")
    # install cgpt and futility
    if os.path.exists("/usr/bin/apt"):
        bash("apt install cgpt vboot-kernel-utils -y")
    elif os.path.exists("/usr/bin/pacman"):
        bash("pacman -S cgpt vboot-utils --noconfirm")
    elif os.path.exists("/usr/bin/dnf"):
        bash("dnf install cgpt vboot-utils --assumeyes")
    else:
        print("\033[91m" + "cgpt and futility not found, please install them using your disotros package manager"
              + "\033[0m")
        exit(1)


# download kernel files from GitHub
def download_kernel() -> None:
    print("\033[96m" + "Downloading kernel binaries from github" + "\033[0m")
    if args.dev_build:
        url = "https://github.com/eupnea-linux/kernel/releases/download/dev-build/"
    elif args.mainline:
        url = "https://github.com/eupnea-linux/mainline-kernel/releases/latest/download/"
    else:
        url = "https://github.com/eupnea-linux/kernel/releases/latest/download/"
    try:
        if args.mainline:
            urlretrieve(f"{url}bzImage", filename="/tmp/eupnea-update/bzImage")
            urlretrieve(f"{url}modules.tar.xz", filename="/tmp/eupnea-update/modules.tar.xz")
        else:
            if args.alt:
                print("Downloading alt kernel")
                urlretrieve(f"{url}bzImage.alt", filename="/tmp/eupnea-update/bzImage")
                urlretrieve(f"{url}modules.alt.tar.xz", filename="/tmp/eupnea-update/modules.tar.xz")
            elif args.exp:
                print("Downloading experimental 5.15 kernel")
                urlretrieve(f"{url}bzImage.exp", filename="/tmp/eupnea-update/bzImage")
                urlretrieve(f"{url}modules.exp.tar.xz", filename="/tmp/eupnea-update/modules.tar.xz")
            else:
                urlretrieve(f"{url}bzImage", filename="/tmp/eupnea-update/bzImage")
                urlretrieve(f"{url}modules.tar.xz", filename="/tmp/eupnea-update/modules.tar.xz")
    except URLError:
        print("\033[91m" + "Failed to reach github. Check your internet connection and try again" + "\033[0m")
        exit(1)


# Configure distro agnostic options
def flash_kernel() -> None:
    print("\n\033[96m" + "Flashing new kernel" + "\033[0m")
    print("Extracting kernel modules")
    rmdir("/mnt/eupnea_rootfs/lib/modules", ignore_errors=True)
    Path("/mnt/eupnea_rootfs/lib/modules").mkdir(parents=True, exist_ok=True)
    # modules tar contains /lib/modules, so it's extracted to / and --skip-old-files is used to prevent overwriting
    # other files in /lib
    bash(f"tar xpf /tmp/eupnea-update/modules.tar.xz --skip-old-files -C /mnt/eupnea_rootfs/ --checkpoint=.10000")
    print("")  # break line after tar
    print("Extracting kernel headers")
    # TODO: extract kernel headers
    print("")
    # get uuid of rootfs partition
    rootfs_partuuid = sp.run([f"blkid -o value -s PARTUUID {device}2"], shell=True,
                             capture_output=True).stdout.decode("utf-8").strip()
    # read and modify kernel flags
    try:
        with open("../configs/kernel.flags", "r") as file:
            temp = file.read().replace("${USB_ROOTFS}", rootfs_partuuid).strip()
    except FileNotFoundError:
        with open("configs/kernel.flags", "r") as file:
            temp = file.read().replace("${USB_ROOTFS}", rootfs_partuuid).strip()
    with open("kernel.flags", "w") as file:
        file.write(temp)
    print("Signing kernel")
    bash("futility vbutil_kernel --arch x86_64 --version 1 --keyblock /usr/share/vboot/devkeys/kernel.keyblock"
         + " --signprivate /usr/share/vboot/devkeys/kernel_data_key.vbprivk --bootloader kernel.flags" +
         " --config kernel.flags --vmlinuz /tmp/eupnea-update/bzImage --pack /tmp/eupnea-update/bzImage.signed")
    print("Flashing kernel")
    bash(f"dd if=/tmp/eupnea-update/bzImage.signed of={device}1")


if __name__ == "__main__":
    # Elevate script to root
    if os.geteuid() != 0:
        args = ['sudo', sys.executable] + sys.argv + [os.environ]
        os.execlpe('sudo', *args)
    args = process_args()
    if args.dev_build:
        print("\033[93m" + "Using dev release" + "\033[0m")
    if args.alt:
        print("\033[93m" + "Using alt kernel" + "\033[0m")
    if args.exp:
        print("\033[93m" + "Using experimental kernel" + "\033[0m")
    if args.mainline:
        print("\033[93m" + "Using mainline kernel" + "\033[0m")
    if args.local_path:
        print("\033[93m" + "Using local path" + "\033[0m")
    # get rootfs partition from user
    device = input("Please enter the device (e.g. /dev/sda) and press enter: \n").strip()
    if device.endswith("/"):
        device = device[:-1]

    prepare_host()
    if args.local_path is None:
        # Print download progress in terminal
        t = Thread(target=download_kernel)
        t.start()
        sleep(1)
        while t.is_alive():
            sys.stdout.flush()
            print(".", end="")
            sleep(1)
        print("")
    else:
        if not args.local_path.endswith("/"):
            kernel_path = f"{args.local_path}/"
        else:
            kernel_path = args.local_path
        print("\033[96m" + "Using local kernel files" + "\033[0m")
        bash(f"cp {kernel_path}bzImage /tmp/eupnea-update/bzImage")
        bash(f"cp {kernel_path}modules.tar.xz /tmp/eupnea-update/modules.tar.xz")
    flash_kernel()
    print("\033[92m" + "Kernel update complete!" + "\033[0m")
