import trio

from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.service_container import ServiceContainer


async def main():
    print("Initializing ServiceContainer...")
    container = ServiceContainer(Settings())

    # We need to mock the API key if it's not set, to allow instantiation
    if not container.config.GOOGLE_API_KEY:
        print(
            "WARNING: GOOGLE_API_KEY not set. Setting a dummy key for testing instantiation."
        )
        container.config.GOOGLE_API_KEY = "dummy_key_for_testing"

    print("Getting llm_service (default)...")
    service_default = container.get("llm_service")

    print("Getting llm_service_intake...")
    service_intake = container.get("llm_service_intake")

    print("Getting llm_service_assessment...")
    service_assessment = container.get("llm_service_assessment")

    print("\n--- Verification Results ---")

    # Check if they are the same object
    is_same_intake = service_default is service_intake
    is_same_assessment = service_intake is service_assessment

    print(f"Default service ID: {id(service_default)}")
    print(f"Intake service ID:  {id(service_intake)}")
    print(f"Assess service ID:  {id(service_assessment)}")

    print(f"Model Names:")
    print(f"  Default: {service_default.model_name}")
    print(f"  Intake:  {service_intake.model_name}")
    print(f"  Assess:  {service_assessment.model_name}")

    if is_same_intake and is_same_assessment:
        print(
            "\n[SUCCESS] Services are the SAME object instance. Rate limiting is shared."
        )
    else:
        print(
            "\n[FAIL] Services are DIFFERENT object instances. Rate limiting is NOT shared."
        )


if __name__ == "__main__":
    trio.run(main)
