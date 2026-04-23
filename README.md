# Home Assistant Planetpod Integration

A Home Assistant integration for Planetpod devices.

## Installation

### Via HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Custom repositories"
3. Add this repository: `https://github.com/marcospieras/home-assistant-planetpod`
4. Click "Install"
5. Restart Home Assistant

### Manual Installation

1. Clone this repository into `config/custom_components/`
2. Restart Home Assistant

## Configuration

After installation, add the integration via Home Assistant UI:

1. Go to Settings → Devices & Services → Create Automation
2. Select "Planetpod" from the list
3. Enter your Planetpod API configuration:
   - **API URL**: The endpoint URL (e.g., `https://api.example.com`)
   - **API Key**: Your Planetpod Open API token (generated in the Planetpod app)

## Features

- Automatic discovery of Planetpod devices
- Real-time status monitoring
- Configurable polling interval
- Full Home Assistant integration

## Requirements

- Home Assistant 2023.12.0 or later
- Planetpod device accessible from Home Assistant

## Support

For issues, questions, or contributions, please visit:
https://github.com/marcospieras/home-assistant-planetpod
