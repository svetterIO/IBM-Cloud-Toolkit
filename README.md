<h1 align="center"><img src="docs/images/IBM_Cloud_logo.png" alt="IBM Cloud" width=300 height=214></h1>

# IBM Cloud ToolKit
A collection of scripts for enumeration of IBM Cloud resources and identification of weak security settings.
Available as **Bash** (Linux/macOS) and **Python 3** (Linux, macOS, Windows).

## Why was this project created?

This toolkit is intended to automate the enumeration of resources and security settings during penetration testing engagements on IBM Cloud accounts. Manual enumeration is time consuming, repetitive, tedious and prone to human error, especially when dealing with complex cloud environments. This collection of scripts aims to improve efficiency, and ensure more accurate coverage of IBM Cloud assets and configurations.

While there are several well-established open-source tools for major cloud providers like AWS and Azure, there are very few similar initiatives focused on IBM Cloud. This project was created to help fill that gap and provide the IBM Cloud community with tools for security assessments and resource inventory.

Contributions and community feedback are welcome! If you find these scripts useful, have suggestions for improvements, feature requests, or want to contribute in any way, feel free to open an issue or submit a PR.

---

## Repository Layout

```
IBM-Cloud-Toolkit/
├── bash/           Bash modules, utils.sh, ibm_cloud_enum.sh
├── python/         Python modules, utils.py, ibm_cloud_enum.py
├── install/        IBM Cloud CLI installers (Bash, PowerShell, Python)
├── docs/
│   └── images/     README images
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Prerequisites

### Permissions
Required permissions may vary depending on the services being audited. At minimum, reader/viewer privileges should be assigned:

![IBM Cloud recommended permissions](docs/images/IBMCloud_permissions.png)

### Bash implementation
- **IBM Cloud CLI** – see [Installation](#ibm-cloud-cli-installation) below
- **jq** – lightweight command-line JSON processor
- **Bash 4.3 or later** – on macOS, install Homebrew's Bash and ensure it is in your `PATH`
- Authenticated session via `ibmcloud login`

### Python implementation
- **Python 3.8+**
- **IBM Cloud CLI** – the Python scripts call the CLI for authentication and plugin commands
- Authenticated session via `ibmcloud login`
- No external Python packages required (standard library only)

---

## IBM Cloud CLI Installation

### Linux / macOS

Use the provided script to install the CLI and all required plugins:

```bash
bash install/install_ibmcloud_cli.sh
```

Or install manually:

```bash
# macOS
curl -fsSL https://clis.cloud.ibm.com/install/osx | sh

# Linux
curl -fsSL https://clis.cloud.ibm.com/install/linux | sh
```

### Windows

Use the provided PowerShell script:

```powershell
powershell -ExecutionPolicy Bypass -File install\install_ibmcloud_cli.ps1
```

Or download the installer directly from the [IBM Cloud CLI releases page](https://github.com/IBM-Cloud/ibm-cloud-cli-release/releases).

### Cross-platform (Python)

```bash
python install/install_ibmcloud_cli.py   # Linux/macOS
python install\install_ibmcloud_cli.py   # Windows
```

### Plugin Installation

After installing the CLI, install the required plugins:

```bash
ibmcloud plugin install cloud-databases
ibmcloud plugin install vpc-infrastructure
ibmcloud plugin install schematic
ibmcloud plugin install schematics
ibmcloud plugin install cloud-object-storage
ibmcloud plugin install container-registry
ibmcloud plugin install ks
ibmcloud plugin install sl
ibmcloud plugin install code-engine
```

---

## Python Setup

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Windows (cmd)

```cmd
python -m venv venv
venv\Scripts\activate.bat
python -m pip install -r requirements.txt
```

> **Note:** The Python implementation uses only the standard library. `requirements.txt` is provided for tooling compatibility; no packages need to be installed for normal use.

---

## Quick Start

![ibm_cloud_enum.sh execution](docs/images/ibm_cloud_enum.png)

### Bash (Linux / macOS)

```bash
bash/ibm_cloud_enum.sh
```

### Python

```bash
# Linux / macOS
python3 python/ibm_cloud_enum.py

# Windows
python python\ibm_cloud_enum.py
```

---

## Usage

Each script accepts a `-h` flag for usage information. Example for `get_api_keys`:

```
$ python3 python/get_api_keys.py -h
usage: get_api_keys.py [-h] [-o OUTPUT_DIR] [-f OUTPUT_FILE] [-d ROTATION_DAYS] [-v]

Enumerate IBM Cloud API keys and flag non-rotated ones.

options:
  -h            show this help message and exit
  -o OUTPUT_DIR  Output folder (default: 'output')
  -f OUTPUT_FILE Output file name (default: 'api_keys.txt')
  -d ROTATION_DAYS  Rotation threshold in days (default: 90)
  -v            Enable debug output
```

---

## Scripts

The Bash and Python versions expose the same options and produce the same output files.

#### - [ibm_cloud_enum](bash/ibm_cloud_enum.sh) / [ibm_cloud_enum.py](python/ibm_cloud_enum.py)
Executes all enumeration scripts against the IBM Cloud Account.

#### - [get_custom_roles](bash/get_custom_roles.sh) / [get_custom_roles.py](python/get_custom_roles.py)
Enumerates custom IAM roles to be verified for excessive privileges granted to users.

#### - [get_users](bash/get_users.sh) / [get_users.py](python/get_users.py)
Enumerates existing users and identifies any with state different than ACTIVE.

#### - [get_user_policies](bash/get_user_policies.sh) / [get_user_policies.py](python/get_user_policies.py)
Identifies users with access policies assigned directly (not via groups).

#### - [get_api_keys](bash/get_api_keys.sh) / [get_api_keys.py](python/get_api_keys.py)
Enumerates existing API Keys and identifies those not rotated within a configurable period (default: 90 days).

#### - [get_mfa](bash/get_mfa.sh) / [get_mfa.py](python/get_mfa.py)
Retrieves the IBM Cloud account identity settings and determines the MFA requirement status.

#### - [get_regions](bash/get_regions.sh) / [get_regions.py](python/get_regions.py)
Enumerates enabled regions on the IBM Cloud account.

#### - [get_floating_IPs](bash/get_floating_IPs.sh) / [get_floating_IPs.py](python/get_floating_IPs.py)
Enumerates all floating IPs in each enabled IBM Cloud region.

#### - [get_VSIs](bash/get_VSIs.sh) / [get_VSIs.py](python/get_VSIs.py)
Enumerates all VSIs (IBM Cloud VMs) in each enabled IBM Cloud region. Also generates a separate file for VSIs with metadata enabled.

#### - [get_buckets](bash/get_buckets.sh) / [get_buckets.py](python/get_buckets.py)
Enumerates all IBM Cloud Object Storage buckets in the account.

#### - [get_buckets_files](bash/get_buckets_files.sh) / [get_buckets_files.py](python/get_buckets_files.py)
Lists all files in existing IBM Cloud Object Storage buckets. **Note:** Disabled for automatic execution in the runner scripts due to potentially long execution times. Run manually.

#### - [download_buckets_files](bash/download_buckets_files.sh) / [download_buckets_files.py](python/download_buckets_files.py)
Downloads files from all IBM Cloud Object Storage buckets. Supports flattening and overwrite options.

#### - [get_schematics](bash/get_schematics.sh) / [get_schematics.py](python/get_schematics.py)
Enumerates all IBM Cloud Schematics workspaces in each enabled region. Output can be reviewed with [TruffleHog](https://github.com/trufflesecurity/trufflehog) or [detect-secrets](https://github.com/Yelp/detect-secrets) to identify secrets stored in variables.

#### - [get_clusters](bash/get_clusters.sh) / [get_clusters.py](python/get_clusters.py)
Enumerates all IBM Cloud Kubernetes/Openshift clusters. Also generates a separate file for clusters with public endpoint enabled.

#### - [get_databases](bash/get_databases.sh) / [get_databases.py](python/get_databases.py)
Enumerates all IBM Cloud Databases. Also generates a separate file for databases with public endpoint enabled.

#### - [get_security_groups](bash/get_security_groups.sh) / [get_security_groups.py](python/get_security_groups.py)
Enumerates all IBM Cloud VPC security groups and identifies overly permissive inbound rules.

#### - [get_code_engine](bash/get_code_engine.sh) / [get_code_engine.py](python/get_code_engine.py)
Enumerates all IBM Cloud Code Engine projects. For each project, retrieves Applications (including environment variables and public endpoint status), Functions, ConfigMaps, and Secrets.

---

## Installers

| File | Platform | Description |
|------|----------|-------------|
| [install/install_ibmcloud_cli.sh](install/install_ibmcloud_cli.sh) | Linux / macOS | Bash installer with plugin support |
| [install/install_ibmcloud_cli.ps1](install/install_ibmcloud_cli.ps1) | Windows | PowerShell installer with plugin support |
| [install/install_ibmcloud_cli.py](install/install_ibmcloud_cli.py) | All | Python cross-platform installer |

---

## Recent Changes

### Version 2.0
- **Python Implementation**: Added a full Python 3 implementation of every Bash module. The Python version works on Linux, macOS and Windows without requiring `jq` or `curl`.
- **Repository Reorganization**: Bash scripts moved to `bash/`, Python scripts to `python/`, installers to `install/`, and images to `docs/images/`.
- **Cross-platform Installers**: Added `install/install_ibmcloud_cli.ps1` (Windows PowerShell) and `install/install_ibmcloud_cli.py` (cross-platform Python) with plugin installation support.
- **Line-Ending Config**: Added `.gitattributes` (LF for `.sh`/`.py`, CRLF for `.ps1`) and `.editorconfig` for consistent checkout across all operating systems.

### Version 1.2
- **CLI-Based Authentication**: Removed IBMCLOUD_API_KEY environment variable requirement. Access tokens are now retrieved directly from authenticated IBM Cloud CLI sessions (`ibmcloud login`), supporting environments where API key creation is restricted.
- **Kubernetes Clusters**: Added ingress subdomain retrieval.
- **Debug Mode**: Added two-level debug modes across enumeration scripts, safe `-v` flag for commands and progress visibility with token-redacted output, and `-d` for full debug.
- **Parallel Processing**: Performance improvements via parallel API requests in some scripts.
- **Resource Statistics**: Display totals and statistics for all resources (e.g., total users, buckets, VSIs).
- **JSON Validation**: Validate all API responses and graceful error handling.
- **Enhanced Output**: List resources on stdout with organized formatting while detailed results are saved to output files.

### Version 1.1
- **IBM Account Identity Settings**: Retrieves IBM Cloud account identity settings.
- **MFA Requirement**: Verifies whether MFA is enforced at the account level and detects any user-specific MFA configurations.
- **DB2 Database**: Adds support for identifying IBM Cloud DB2 database instances.
- **Code Engine**: Enumerates IBM Cloud Code Engine projects.
- **Security Groups**: Enumerates security groups and flags overly permissive rules.
- **Execution Change**: `get_buckets_files.sh` is now disabled in `ibm_cloud_enum.sh` and must be executed manually.

---

## TODO
- Support for handling multiple IBM Cloud accounts in batch mode across all enumeration scripts.
- Implement pagination support in all modules.
- Support Cloudant DBs.
- Retrieve public endpoints (hostname:port) of public DBs.
- Enumerate Load Balancer resources.

---

## Author
Heber Blain Gonçalves

- [linkedin.com/hebergoncalves/](https://linkedin.com/in/hebergoncalves/)
- [github.com/manotux](https://github.com/manotux)

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Disclaimer

This project is a personal and community-driven initiative and is not affiliated with, endorsed by, or supported by IBM or IBM Cloud. IBM and IBM Cloud are not responsible for this project or any outcomes resulting from its use.

This software is provided as-is, with no guarantees. Use it at your own risk. The author and contributors are not responsible for any problems, data loss, or damage that may happen.
