#!/usr/bin/env python3
import sys
import os
import argparse
import json
import asyncio

# Add src to python path to access database module
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

try:
    from src.database import init_db, update_pin_mapping, delete_pin_mapping, get_all_pin_mappings, PinMapping
except ImportError as e:
    print(f"Error importing database module: {e}")
    sys.exit(1)

async def notify_daemon():
    try:
        import websockets
        async with websockets.connect("ws://localhost:9002") as ws:
            payload = {
                "type": "pin_mapping",
                "action": "reload"
            }
            await ws.send(json.dumps(payload))
            response = await ws.recv()
            resp_data = json.loads(response)
            if resp_data.get("status") == "ok":
                print("Daemon successfully reloaded pin mappings.")
            else:
                print(f"Daemon reload failed: {resp_data.get('message')}")
    except ImportError:
        print("Note: 'websockets' library not installed. Cannot notify daemon to reload automatically.")
    except Exception as e:
        print(f"Note: Could not notify daemon to reload (is it running?): {e}")

def notify_daemon_sync():
    try:
        asyncio.run(notify_daemon())
    except Exception:
        pass

def show_mappings():
    mappings = PinMapping.select()
    if not mappings:
        print("No pin mappings found.")
        return
        
    print("-" * 50)
    print(f"{'Logical Pin':<15} | {'Physical Pin':<15} | {'Description'}")
    print("-" * 50)
    for m in mappings:
        print(f"{m.logical_pin:<15} | {m.physical_pin:<15} | {m.description}")
    print("-" * 50)

def main():
    init_db()
    
    parser = argparse.ArgumentParser(description="Xploria RPi Daemon - Pin Configuration CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # List command
    subparsers.add_parser("list", help="List all pin mappings")
    
    # Set command
    set_parser = subparsers.add_parser("set", help="Set a pin mapping (logical to physical)")
    set_parser.add_argument("logical_pin", type=int, help="The logical pin number (e.g. 1)")
    set_parser.add_argument("physical_pin", type=int, help="The physical GPIO pin number (e.g. 17)")
    set_parser.add_argument("--desc", type=str, help="Description for this pin", default="")
    
    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a pin mapping")
    delete_parser.add_argument("logical_pin", type=int, help="The logical pin number to delete")
    
    # Interactive mode command
    subparsers.add_parser("interactive", help="Start interactive configuration mode")
    
    args = parser.parse_args()
    
    if args.command == "list":
        show_mappings()
        
    elif args.command == "set":
        update_pin_mapping(args.logical_pin, args.physical_pin, args.desc)
        print(f"Successfully mapped Logical Pin {args.logical_pin} -> Physical Pin {args.physical_pin}")
        notify_daemon_sync()
        
    elif args.command == "delete":
        delete_pin_mapping(args.logical_pin)
        print(f"Successfully deleted mapping for Logical Pin {args.logical_pin}")
        notify_daemon_sync()
        
    elif args.command == "interactive":
        interactive_mode()
        
    else:
        parser.print_help()

def interactive_mode():
    print("=== Interactive Pin Configuration ===")
    while True:
        print("\nOptions:")
        print("1. List current pin mappings")
        print("2. Set/Update a pin mapping")
        print("3. Delete a pin mapping")
        print("4. Exit")
        
        choice = input("Select an option (1-4): ").strip()
        
        if choice == '1':
            show_mappings()
            
        elif choice == '2':
            try:
                logical = int(input("Enter Logical Pin (e.g. 1): ").strip())
                physical = int(input(f"Enter Physical Pin for Logical {logical}: ").strip())
                desc = input("Enter description (optional): ").strip()
                update_pin_mapping(logical, physical, desc)
                print(f"Success! Logical Pin {logical} is now mapped to Physical Pin {physical}.")
                notify_daemon_sync()
            except ValueError:
                print("Error: Pin numbers must be integers.")
                
        elif choice == '3':
            try:
                logical = int(input("Enter Logical Pin to delete: ").strip())
                delete_pin_mapping(logical)
                print(f"Deleted mapping for Logical Pin {logical}.")
                notify_daemon_sync()
            except ValueError:
                print("Error: Pin number must be an integer.")
                
        elif choice == '4':
            print("Exiting.")
            break
        else:
            print("Invalid choice, please select 1-4.")

if __name__ == "__main__":
    main()
