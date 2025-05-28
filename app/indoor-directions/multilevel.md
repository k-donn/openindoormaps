# Multi-level routing plan

- Add a level property to each node in the graph
- Only render current level's POIs
- Add level check for poi-map.ts#34 to prevent overlap
- Change IndoorDirections.findNearestGraphPoint to have level consideration
- Add level info for snap points
- Change IndoorDirections.calculateDirections to put level into on each segment
- Change IndoorDirections.draw to only draw the part of the segment corresponding to the selected level
