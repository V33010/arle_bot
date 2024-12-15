from validators.skin import SkinChromas

def map_row_to_skin_chromas(row):
    inner = row[0]
    s = SkinChromas(
        uuid=inner[4],  # 5th column is the uuid
        displayName=inner[1],  # 2nd column is the display name
        displayIcon=inner[5],  # 6th column is display icon
        fullRender=inner[6],  # 7th column is full render
        swatch=inner[7],  # 8th column is swatch
        streamedVideo=inner[8]
        if inner[8] != "NULL"
        else None,  # 9th column is streamed video
        assetPath=inner[9],  # 10th column is asset path
        pickrate=inner[3],  # 4th column is pickrate
        total_occurance_rate=inner[2],  # 3rd column is total occurrence rate
    )
    return s
