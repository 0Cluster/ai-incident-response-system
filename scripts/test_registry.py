from app.automation.registry import registry

print(registry.list())

print(registry.get("log"))
print(registry.get("webhook"))
