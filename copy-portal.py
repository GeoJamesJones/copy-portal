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

    

if __name__ == "__main__":
    main()