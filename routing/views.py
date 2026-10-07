from urllib.parse import urlencode

from django.shortcuts import redirect, render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from routing.serializers import RouteRequestSerializer
from routing.services import geocoding, osrm
from routing.services.optimizer import RouteInfeasibleError
from routing.services.planner import plan_route


@api_view(["GET", "POST"])
def route_view(request):
    """Plan a fuel-optimised route.

    Accepts ``start`` and ``finish`` as query params (GET) or JSON body (POST).
    Returns the route geometry, the cost-optimal fuel stops, and the total
    fuel cost for a 500-mile-range, 10-mpg vehicle.
    """
    data = request.query_params if request.method == "GET" else request.data
    serializer = RouteRequestSerializer(data=data)
    serializer.is_valid(raise_exception=True)

    try:
        result = plan_route(
            start=serializer.validated_data["start"],
            finish=serializer.validated_data["finish"],
        )
    except geocoding.GeocodingError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except RouteInfeasibleError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except osrm.RoutingError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(result)


#: Canonical demo trip, used by both the reset endpoint and the map defaults.
DEMO_START = "Chicago, IL"
DEMO_FINISH = "Houston, TX"


def demo_reset(request):
    """Reset the demo to a clean, known state.

    Redirects to the map pre-loaded with the canonical Chicago -> Houston trip,
    ignoring whatever was typed before. Handy as the single URL to open at the
    start of a screen recording so the demo always looks the same.
    """
    query = urlencode({"start": DEMO_START, "finish": DEMO_FINISH})
    return redirect(f"/map?{query}")


def map_view(request):
    """Render an interactive Leaflet map of the route and its fuel stops.

    Convenience page for demos: pass ``?start=...&finish=...`` and it fetches the
    JSON API client-side and draws it. No API key required (OpenStreetMap tiles).
    """
    return render(
        request,
        "routing/map.html",
        {
            "start": request.GET.get("start", DEMO_START),
            "finish": request.GET.get("finish", DEMO_FINISH),
        },
    )
