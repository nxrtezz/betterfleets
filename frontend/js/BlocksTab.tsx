import React, { useState, useEffect } from "react";

type TripFromAPI = {
  id: number;
  vehicle_journey_code: string;
  ticket_machine_code: string;
  block: string;
  start: string;
  end: string;
  headsign: string;
  service: {
    id: number;
    line_name: string;
    slug: string;
    mode: string;
  };
  operator: {
    noc: string;
    name: string;
    vehicle_mode: string;
    slug: string;
  };
  notes: any[];
  times: any[];
};

type Block = {
  name: string;
  services: string[];
  trips: TripFromAPI[];
};

type BlocksTabProps = {
  operatorNoc: string;
  date: string;
};

export default function BlocksTab({ operatorNoc, date }: BlocksTabProps) {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [selectedBlock, setSelectedBlock] = useState<Block | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchTrips = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          operator: operatorNoc,
          date: date,
        });
        const response = await fetch(`/api/trips/?${params.toString()}`);
        if (!response.ok) {
          throw new Error("Failed to fetch trips");
        }
        const data = await response.json();
        
        // Group trips by block
        const blockMap = new Map<string, TripFromAPI[]>();
        data.results.forEach((trip: TripFromAPI) => {
          if (trip.block) {
            if (!blockMap.has(trip.block)) {
              blockMap.set(trip.block, []);
            }
            blockMap.get(trip.block)!.push(trip);
          }
        });

        // Convert to blocks array with unique services
        const blocksArray: Block[] = Array.from(blockMap.entries()).map(
          ([blockName, trips]) => {
            const services = Array.from(
              new Set(trips.map((trip) => trip.service.line_name))
            ).sort();
            return {
              name: blockName,
              services,
              trips,
            };
          }
        );

        // Sort blocks by name
        blocksArray.sort((a, b) => a.name.localeCompare(b.name));
        setBlocks(blocksArray);
      } catch (err) {
        setError(err instanceof Error ? err.message : "An error occurred");
      } finally {
        setLoading(false);
      }
    };

    fetchTrips();
  }, [operatorNoc, date]);

  const calculateDuration = (start: string, end: string): string => {
    const startDate = new Date(`2000-01-01T${start}`);
    const endDate = new Date(`2000-01-01T${end}`);
    const diffMs = endDate.getTime() - startDate.getTime();
    const diffMins = Math.round(diffMs / 60000);
    return `${diffMins}m`;
  };

  if (loading) {
    return <p>Loading blocks...</p>;
  }

  if (error) {
    return <p className="error">Error: {error}</p>;
  }

  if (selectedBlock) {
    return (
      <div>
        <button
          onClick={() => setSelectedBlock(null)}
          className="button"
          style={{ marginBottom: "1rem" }}
        >
          ← Back to blocks
        </button>
        <h2>Block {selectedBlock.name}</h2>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th scope="col">Start</th>
                <th scope="col">Duration</th>
                <th scope="col">Service</th>
                <th scope="col">Direction</th>
              </tr>
            </thead>
            <tbody>
              {selectedBlock.trips.map((trip) => (
                <tr key={trip.id}>
                  <td className="tabular">{trip.start.slice(0, 5)}</td>
                  <td className="tabular">
                    {calculateDuration(trip.start, trip.end)}
                  </td>
                  <td>{trip.service.line_name}</td>
                  <td>{trip.headsign}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (blocks.length === 0) {
    return <p>No blocks are listed for this date.</p>;
  }

  return (
    <div
      style={{
        display: "grid",
        gap: "1rem",
        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
      }}
    >
      {blocks.map((block) => (
        <div
          key={block.name}
          className="card"
          style={{
            padding: "1rem",
            cursor: "pointer",
            transition: "border-color 0.15s",
          }}
          onClick={() => setSelectedBlock(block)}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "var(--border-color-darker)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "var(--border-color)";
          }}
        >
          <h3 style={{ margin: "0 0 0.5rem 0" }}>{block.name}</h3>
          <p style={{ margin: 0, color: "var(--secondary-text-color)" }}>
            {block.services.join(", ")}
          </p>
        </div>
      ))}
    </div>
  );
}
