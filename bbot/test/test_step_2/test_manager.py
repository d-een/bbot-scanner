from ..bbot_fixtures import *  # noqa: F401


def test_manager(bbot_config, bbot_scanner):
    dns_config = OmegaConf.merge(
        default_config, OmegaConf.create({"dns_resolution": True, "scope_report_distance": 1})
    )

    # test _emit_event
    results = []
    output = []
    success_callback = lambda e: results.append("success")
    scan1 = bbot_scanner("127.0.0.1", modules=["ipneighbor"], output_modules=["human"], config=dns_config)
    scan1.load_modules()
    module = scan1.modules["ipneighbor"]
    module.scope_distance_modifier = 0
    module.queue_event = lambda e: results.append(e)
    output_module = scan1.modules["human"]
    output_module.queue_event = lambda e: output.append(e)
    scan1.status = "RUNNING"
    manager = scan1.manager
    # manager.distribute_event = lambda e: results.append(e)
    localhost = scan1.make_event("127.0.0.1", source=scan1.root_event, tags=["localhost"])

    class DummyModule1:
        _type = "output"
        suppress_dupes = True

    class DummyModule2:
        _type = "DNS"
        suppress_dupes = True

    class DummyModule3:
        _type = "DNS"
        suppress_dupes = True

    localhost.module = DummyModule1()
    # make sure abort_if works as intended
    manager._emit_event(localhost, abort_if=lambda e: e.module._type == "output")
    assert len(results) == 0
    manager.events_accepted.clear()
    # make sure success_callback works as intended
    manager._emit_event(
        localhost, on_success_callback=success_callback, abort_if=lambda e: e.module._type == "plumbus"
    )
    assert localhost in results
    assert "success" in results
    results.clear()
    # make sure deduplication is working
    localhost2 = scan1.make_event("127.0.0.1", source=scan1.root_event, tags=["localhost2"])
    manager._emit_event(localhost2)
    assert len(results) == 0
    # make sure dns resolution is working
    googledns = scan1.make_event("8.8.8.8", source=scan1.root_event)
    googledns.module = DummyModule2()
    googledns.source = "asdf"
    googledns.make_in_scope()
    event_children = []
    manager.emit_event = lambda e, *args, **kwargs: event_children.append(e)
    manager._emit_event(googledns)
    assert len(event_children) > 0
    assert googledns in results
    assert googledns in output
    results.clear()
    output.clear()
    event_children.clear()
    # make sure deduplication catches the same event
    manager._emit_event(googledns)
    assert len(output) == 0
    assert len(results) == 0
    assert len(event_children) == 0
    output.clear()
    event_children.clear()
    # make sure _force_output overrides dup detection
    googledns._force_output = True
    manager._emit_event(googledns)
    assert googledns in output
    assert len(event_children) == 0
    googledns._force_output = False
    results.clear()
    event_children.clear()
    # same dns event but different source
    source_event = manager.scan.make_event("1.2.3.4", "IP_ADDRESS", source=manager.scan.root_event)
    source_event._resolved.set()
    googledns.source = source_event
    manager._emit_event(googledns)
    assert len(event_children) == 0
    assert googledns in output


def test_scope_distance(bbot_scanner, bbot_config):
    # event filtering based on scope_distance
    scan1 = bbot_scanner(
        "127.0.0.1", "evilcorp.com", modules=["ipneighbor"], output_modules=["json"], config=bbot_config
    )
    scan1.status = "RUNNING"
    scan1.load_modules()
    module = scan1.modules["ipneighbor"]
    module_queue = module.incoming_event_queue.queue
    output_module = scan1.modules["json"]
    output_queue = output_module.incoming_event_queue.queue
    manager = scan1.manager
    test_event1 = scan1.make_event("127.0.0.1", source=scan1.root_event)

    assert scan1.scope_search_distance == 1
    assert scan1.scope_report_distance == 0
    assert module.scope_distance_modifier == 0

    # test _emit_event() with scope_distance == 0
    manager._emit_event(test_event1)
    assert test_event1.scope_distance == 0
    assert test_event1._internal == False
    assert test_event1 in output_queue
    assert test_event1 in module_queue

    test_event2 = scan1.make_event("2.3.4.5", source=test_event1)
    test_event3 = scan1.make_event("3.4.5.6", source=test_event2)
    test_event4 = scan1.make_event("4.5.6.7", source=test_event2)
    test_event4._force_output = True
    dns_event = scan1.make_event("evilcorp.com", source=scan1.root_event)

    # non-watched event type
    manager._emit_event(dns_event)
    assert dns_event.scope_distance == 0
    assert dns_event in output_queue
    assert dns_event not in module_queue

    # test _emit_event() with scope_distance == 1
    assert test_event2.scope_distance == 1
    manager._emit_event(test_event2)
    assert test_event2.scope_distance == 1
    assert test_event2._internal == True
    assert test_event2 not in output_queue
    assert test_event2 in module_queue
    valid, reason = module._event_postcheck(test_event2)
    assert valid

    # test _emit_event() with scope_distance == 2
    assert test_event3.scope_distance == 2
    manager._emit_event(test_event3)
    assert test_event3.scope_distance == 2
    assert test_event3._internal == True
    assert test_event3 not in output_queue
    assert test_event3 in module_queue
    valid, reason = module._event_postcheck(test_event3)
    assert not valid
    assert reason.startswith("its scope_distance (2) exceeds the maximum allowed by the scan")

    # test _emit_event() with scope_distance == 2 and _force_output == True
    assert test_event4.scope_distance == 2
    manager._emit_event(test_event4)
    assert test_event4.scope_distance == 2
    assert test_event4._internal == True
    assert test_event4._force_output == True
    assert test_event4 in output_queue
    assert test_event4 in module_queue
    valid, reason = module._event_postcheck(test_event4)
    assert not valid
    assert reason.startswith("its scope_distance (2) exceeds the maximum allowed by the scan")
