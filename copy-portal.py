import argparse
import json
import tempfile

from arcgis.gis import GIS

def copy_user(target_portal, source_user, password):
    # See if the user has firstName and lastName properties
    try:
        first_name = source_user.firstName
        last_name = source_user.lastName
    except:
        # if not, split the fullName
        full_name = source_user.fullName
        first_name = full_name.split()[0]
        try:
            last_name = full_name.split()[1]
        except:
            last_name = 'NoLastName'

    try:
        # create user
        target_user = target_portal.users.create(source_user.username, password, first_name, 
                                                 last_name, source_user.email, 
                                                 source_user.description, source_user.role)

        # update user properties
        target_user.update(source_user.access, source_user.preferredView,
                           source_user.description, source_user.tags, 
                           source_user.get_thumbnail_link(),
                           culture=source_user.culture, region=source_user.region)
        return target_user
    
    except Exception as Ex:
        print(str(Ex))
        print("Unable to create user "+ source_user.username)
        return None

def copy_group(target, source, source_group):
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            target_group = {}

            for property_name in GROUP_COPY_PROPERTIES:
                target_group[property_name] = source_group[property_name]

            if source_group['access'] == 'org' and target.properties['portalMode'] == 'singletenant':
                #cloning from ArcGIS Online to ArcGIS Enterprise
                target_group['access'] = 'public'

            elif source_group['access'] == 'public'\
                 and source.properties['portalMode'] == 'singletenant'\
                 and target.properties['portalMode'] == 'multitenant'\
                 and 'id' in target.properties:
                    #cloning from ArcGIS Enterprise to ArcGIS Online org
                    target_group['access'] = 'org'

            # Download the thumbnail (if one exists)
            thumbnail_file = None
            if 'thumbnail' in group:
                target_group['thumbnail'] = group.download_thumbnail(temp_dir)

            # Create the group in the target portal
            copied_group = target.groups.create_from_dict(target_group)

            # Reassign all groups to correct owners, add users, and find shared items
            members = group.get_members()
            if not members['owner'] == target_admin_username:
                copied_group.reassign_to(members['owner'])
            if members['users']:
                copied_group.add_users(members['users'])
            return copied_group
        except:
            print("Error creating " + source_group['title'])

def copy_item(target, source_item):
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            item_properties = {}
            for property_name in ITEM_COPY_PROPERTIES:
                item_properties[property_name] = source_item[property_name]

            data_file = None
            
            if source_item.type in TEXT_BASED_ITEM_TYPES:
                # If its a text-based item, then read the text and add it to the request.
                text = source_item.get_data(False)
                item_properties['text'] = text
            
            elif source_item.type in FILE_BASED_ITEM_TYPES:
                # download data and add to the request as a file
                data_file = source_item.download(temp_dir)

            thumbnail_file = source_item.download_thumbnail(temp_dir)
            metadata_file = source_item.download_metadata(temp_dir)

            #find item's owner
            source_item_owner = source.users.search(source_item.owner)[0]
            
            #find item's folder
            item_folder_titles = [f['title'] for f in source_item_owner.folders 
                                  if f['id'] == source_item.ownerFolder]
            folder_name = None
            if len(item_folder_titles) > 0:
                folder_name = item_folder_titles[0]

            #if folder does not exist for target user, create it
            if folder_name:
                target_user = target.users.search(source_item.owner)[0]
                target_user_folders = [f['title'] for f in target_user.folders
                                       if f['title'] == folder_name]
                if len(target_user_folders) == 0:
                    #create the folder
                    target.content.create_folder(folder_name, source_item.owner)
            
            # Add the item to the target portal, assign owner and folder
            target_item = target.content.add(item_properties, data_file, thumbnail_file, 
                                             metadata_file, source_item.owner, folder_name)
            
            #Set sharing (privacy) information
            share_everyone = source_item.access == 'public'
            share_org = source_item.access in ['org', 'public']
            share_groups = []
            if source_item.access == 'shared':
                share_groups = source_item.groups
            
            target_item.share(share_everyone, share_org, share_groups)
            
            return target_item
        
    except Exception as copy_ex:
        print("\tError copying " + source_item.title)
        print("\t" + str(copy_ex))
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="Path to Config JSON", required=True)
    args = parser.parse_args()

    with open(args.config) as config_file:
        config = json.load(config_file)

    source = GIS(config["source-portal"], config["source-portal-username"], config["source-portal-password"])
    print("Connected to source portal at {}".format(config['source-portal']))
    target = GIS(config["target-portal"], config["target-portal-username"], config["target-portal-password"])

    print("Users current in {}".format(config["source-portal"]))
    print("#-----------------------------------")
    source_users = source.users.search('!esri_ & !admin')
    for user in source_users:
        print("#   " + user.username)
        print("#   " + str(user.role))
        print("#-----------------------------------")

    target_users = target.users.search('!esri_ & !admin & !system_publisher')

    for user in source_users:
        print("Creating user: " + user.username)
        copy_user(target, user, 'TestPassword@123')

    print("Successfully copied users from {0} to {1}.".format(config["source-portal"], config["target-portal"]))
    print("Beginning migration of groups.")

    source_groups = source.groups.search("!owner:esri_* & !Basemaps")
    target_groups = target.groups.search("!owner:esri_* & !Basemaps")

    GROUP_COPY_PROPERTIES = ['title', 'description', 'tags', 'snippet', 'phone', 'access', 'isInvitationOnly']

    for group in source_groups:
        print("Creating group: " + group)
        target_group = copy_group(target, source, group)

    print("Successfully copied groups from {0} to {1}.".format(config["source-portal"], config["target-portal"]))
    print("Beginning copy of items.")

    source_items_by_id = {}
    for user in source_users:
        num_items = 0
        num_folders = 0
        print("Collecting item ids for {}".format(user.username), end="\t\t")
        user_content = user.items()
        
        # Get item ids from root folder first
        for item in user_content:
            num_items += 1
            source_items_by_id[item.itemid] = item 
        
        # Get item ids from each of the folders next
        folders = user.folders
        for folder in folders:
            num_folders += 1
            folder_items = user.items(folder=folder['title'])
            for item in folder_items:
                num_items += 1
                source_items_by_id[item.itemid] = item
        
        print("Number of folders {} # Number of items {}".format(str(num_folders), str(num_items)))

    for group in source_groups:
        #iterate through each item shared to the source group
        for group_item in group.content():
            try:
                #get the item
                item = source_items_by_id[group_item.itemid]
                if item is not None:
                    if not 'groups'in item:
                        item['groups'] = []
                    
                    #assign the target portal's corresponding group's name
                    item['groups'].append(group['title'])
            except:
                print("Cannot find item : " + group_item.itemid)

    for key in source_items_by_id.keys():
        item = source_items_by_id[key]
        print("\n{:40s}".format(item.title), end = " # ")
        if 'groups' in item:
            print(item.access, end = " # ")
            print(item.groups, end = "")

    TEXT_BASED_ITEM_TYPES = frozenset(['Web Map', 'Feature Service', 'Map Service','Web Scene',
                                    'Image Service', 'Feature Collection', 
                                    'Feature Collection Template',
                                    'Web Mapping Application', 'Mobile Application', 
                                    'Symbol Set', 'Color Set',
                                    'Windows Viewer Configuration'])

    FILE_BASED_ITEM_TYPES = frozenset(['File Geodatabase','CSV', 'Image', 'KML', 'Locator Package',
                                    'Map Document', 'Shapefile', 'Microsoft Word', 'PDF',
                                    'Microsoft Powerpoint', 'Microsoft Excel', 'Layer Package',
                                    'Mobile Map Package', 'Geoprocessing Package', 'Scene Package',
                                    'Tile Package', 'Vector Tile Package'])

    ITEM_COPY_PROPERTIES = ['title', 'type', 'typeKeywords', 'description', 'tags',
                            'snippet', 'extent', 'spatialReference', 'name',
                            'accessInformation', 'licenseInfo', 'culture', 'url']

    source_target_itemId_map = {}
    for key in source_items_by_id.keys():
        source_item = source_items_by_id[key]

        print("Copying {} \tfor\t {}".format(source_item.title, source_item.owner))
        target_item = copy_item(target, source_item)
        if target_item:
            source_target_itemId_map[key] = target_item.itemid
        else:
            source_target_itemId_map[key] = None

    RELATIONSHIP_TYPES = frozenset(['Map2Service', 'WMA2Code',
                                    'Map2FeatureCollection', 'MobileApp2Code', 'Service2Data',
                                    'Service2Service'])

    for key in source_target_itemId_map.keys():
        source_item = source_items_by_id[key]
        target_itemid = source_target_itemId_map[key]
        target_item = target.content.get(target_itemid)

        print(source_item.title + " # " + source_item.type)
        for relationship in RELATIONSHIP_TYPES:
            try:
                source_related_items = source_item.related_items(relationship)
                for source_related_item in source_related_items:
                    print("\t\t" + source_related_item.title + " # " + 
                        source_related_item.type +"\t## " + relationship)

                    #establish same relationship amongst target items
                    print("\t\t" + "establishing relationship in target portal", end=" ")
                    target_related_itemid = source_target_itemId_map[source_related_item.itemid]
                    target_related_item = target.content.get(target_related_itemid)
                    status = target_item.add_relationship(target_related_item, relationship)
                    print(str(status))
            except Exception as rel_ex:
                print("\t\t Error when checking for " + relationship + " : " + str(rel_ex))
                continue



    

if __name__ == "__main__":
    main()