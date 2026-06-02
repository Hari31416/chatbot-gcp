import json
import subprocess
import os


def main():
    print("🚀 Fetching deployment outputs from Azure...")
    try:
        result = subprocess.run(
            [
                "az",
                "deployment",
                "sub",
                "show",
                "--name",
                "main",
                "--query",
                "properties.outputs",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        outputs = json.loads(result.stdout)
    except Exception as e:
        print(f"❌ Error fetching deployment outputs: {e}")
        return

    def get_output_val(key):
        key_lower = key.lower()
        for k, v in outputs.items():
            if k.lower() == key_lower:
                return v.get("value")
        return None

    env_updates = {
        "AZURE_STORAGE_ACCOUNT_NAME": get_output_val("AZURE_STORAGE_ACCOUNT_NAME"),
        "COSMOS_ENDPOINT": get_output_val("COSMOS_ENDPOINT"),
        "AZURE_KEYVAULT_NAME": get_output_val("AZURE_KEYVAULT_NAME"),
        "AZURE_CONTAINER_REGISTRY": get_output_val("AZURE_CONTAINER_REGISTRY"),
        "AZURE_SWA_DEPLOYMENT_TOKEN": get_output_val("AZURE_SWA_DEPLOYMENT_TOKEN"),
        "AZURE_FUNCTION_APP_NAME": get_output_val("AZURE_FUNCTION_APP_NAME"),
    }

    env_vars = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip()
    else:
        # Load from .env.example if .env does not exist
        if os.path.exists(".env.example"):
            with open(".env.example", "r") as f:
                lines = f.readlines()
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()

    # Update with new Bicep outputs
    for k, v in env_updates.items():
        if v:
            env_vars[k] = v

    # Write back to .env
    with open(".env", "w") as f:
        f.write("# ──────────────────────────────────────────────\n")
        f.write("# Azure Environment Configuration (Auto-Generated)\n")
        f.write("# ──────────────────────────────────────────────\n")
        for k, v in sorted(env_vars.items()):
            f.write(f"{k}={v}\n")

    print("✅ Successfully updated .env with Azure deployment outputs!")


if __name__ == "__main__":
    main()
